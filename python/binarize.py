#!/usr/bin/python

import os
import sys
import matplotlib
matplotlib.use('AGG')
import matplotlib.pyplot as plt
plt.ioff()
import numpy as np
import caffe
import cv2
import scipy.ndimage.morphology


# acceptable image suffixes
IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.tif', '.tiff', '.png', '.bmp', '.ppm', '.pgm')


TILE_SIZE = 512
PADDING_SIZE = 6

# number of subwindows processed by a network in a batch
# Higher numbers speed up processing (only marginally if BATCH_SIZE > 16)
# The larger the batch size, the more memory is consumed (both CPU and GPU)
BATCH_SIZE=1

LEFT_EDGE = -2
TOP_EDGE = -1
MIDDLE = 0
RIGHT_EDGE = 1
BOTTOM_EDGE = 2


def setup_network(network, weights):
	network = caffe.Net(network, weights, caffe.TEST)
	return network


def fprop(network, ims, batchsize=BATCH_SIZE):
	# batch up all transforms at once
	idx = 0
	responses = list()
	while idx < len(ims):
		sub_ims = ims[idx:idx+batchsize]
		network.blobs["data"].reshape(len(sub_ims), 3, ims[0].shape[0], ims[0].shape[1]) 
		for x, im in enumerate(sub_ims):
			transposed = np.transpose(im, [2,0,1])
			transposed = transposed[np.newaxis, :, :, :]
			network.blobs["data"].data[x,:,:,:] = transposed
		idx += batchsize

		# propagate on batch
		network.forward()
		output = np.copy(network.blobs["prob"].data)
		responses.append(output)
		print "Progress %d%%" % int(100 * min(idx, len(ims)) / float(len(ims)))
	return np.concatenate(responses, axis=0)


def predict(network, ims):
	all_outputs = np.squeeze(fprop(network, ims), axis=1)

	high_indices = all_outputs >= 0.5
	predictions = np.zeros_like(all_outputs)
	predictions[high_indices] = 1
	return all_outputs, predictions


def get_subwindows(im):
	height, width, = TILE_SIZE, TILE_SIZE
	y_stride, x_stride, = TILE_SIZE - (2 * PADDING_SIZE), TILE_SIZE - (2 * PADDING_SIZE)
	if (height > im.shape[0]) or (width > im.shape[1]):
		print "Invalid crop: crop dims larger than image (%r with %r)" % (im.shape, tokens)
		exit(1)
	ims = list()
	locations = list()
	y = 0
	y_done = False
	while y  <= im.shape[0] and not y_done:
		x = 0
		if y + height > im.shape[0]:
			y = im.shape[0] - height
			y_done = True
		x_done = False
		while x <= im.shape[1] and not x_done:
			if x + width > im.shape[1]:
				x = im.shape[1] - width
				x_done = True
			locations.append( ((y, x, y + height, x + width), 
					(y + PADDING_SIZE, x + PADDING_SIZE, y + y_stride, x + x_stride),
					 TOP_EDGE if y == 0 else (BOTTOM_EDGE if y == (im.shape[0] - height) else MIDDLE),
					  LEFT_EDGE if x == 0 else (RIGHT_EDGE if x == (im.shape[1] - width) else MIDDLE) 
			) )
			ims.append(im[y:y+height,x:x+width])
			x += x_stride
		y += y_stride

	return locations, ims


def stich_together(locations, subwindows, size, dtype):
	output = np.zeros(size, dtype=dtype)
	for location, subwindow in zip(locations, subwindows):
		outer_bounding_box, inner_bounding_box, y_type, x_type = location
		y_paste, x_paste, y_cut, x_cut, height_paste, width_paste = -1, -1, -1, -1, -1, -1

		if y_type == TOP_EDGE:
			y_cut = 0
			y_paste = 0
			height_paste = TILE_SIZE - PADDING_SIZE
		elif y_type == MIDDLE:
			y_cut = PADDING_SIZE
			y_paste = inner_bounding_box[0]
			height_paste = TILE_SIZE - 2 * PADDING_SIZE
		elif y_type == BOTTOM_EDGE:
			y_cut = PADDING_SIZE
			y_paste = inner_bounding_box[0]
			height_paste = TILE_SIZE - PADDING_SIZE

		if x_type == LEFT_EDGE:
			x_cut = 0
			x_paste = 0
			width_paste = TILE_SIZE - PADDING_SIZE
		elif x_type == MIDDLE:
			x_cut = PADDING_SIZE
			x_paste = inner_bounding_box[1]
			width_paste = TILE_SIZE - 2 * PADDING_SIZE
		elif x_type == RIGHT_EDGE:
			x_cut = PADDING_SIZE
			x_paste = inner_bounding_box[1]
			width_paste = TILE_SIZE - PADDING_SIZE

		output[y_paste:y_paste+height_paste, x_paste:x_paste+width_paste] = subwindow[y_cut:y_cut+height_paste, x_cut:x_cut+width_paste]

	return output


def save_histo(data, fname, title, weights=None):
	if weights is not None:
		weights = weights.flatten()
		
	n, bins, patches = plt.hist(data.flatten(), bins=100, weights=weights, log=True)
	plt.title(title)
	plt.xlabel('Predicted Probability of Foreground')
	plt.ylabel('Pixel Count')
	plt.tick_params(axis='y', which='minor', left='off', right='off')

	plt.savefig(fname)
	plt.clf()
	

def main(network, weights, in_image, out_prefix):
	image = cv2.imread(in_image, cv2.IMREAD_COLOR)
	image = 0.0039 * (image - 127.)

	network = setup_network(network, weights)
	locations, subwindows = get_subwindows(image)
	raw_subwindows, binarized_subwindows = predict(network, subwindows)
	
	binary_result = stich_together(locations, binarized_subwindows, tuple(image.shape[0:2]), dtype=np.uint8)
	binary_result = 255 * (1 - binary_result)
	binary_out_file = out_prefix + "_pred.png"
	cv2.imwrite(binary_out_file, binary_result)

	raw_result = stich_together(locations, raw_subwindows, tuple(image.shape[0:2]), dtype=np.float)
	raw_out_file = out_prefix + "_raw.png"
	cv2.imwrite(raw_out_file, 255 * (1 - raw_result))

	save_histo(raw_result, out_prefix + "_histo_global.png", "Global")

	if len(sys.argv) > 6:
		gt_file = sys.argv[6]
		gt_im = cv2.imread(gt_file, -1) / 255.

		save_histo(raw_result, out_prefix + "_histo_background.png", "Background Pixels", gt_im)

		for x in xrange(3):
			save_histo(raw_result, out_prefix + "_histo_foreground_%d.png" % x, "Foreground Pixels (within %d)" % x, 1 - gt_im)
			gt_im = scipy.ndimage.morphology.binary_erosion(gt_im)
			

if __name__ == "__main__":
	if len(sys.argv) < 4:
		print "USAGE: python binarize.py network weights in_image out_image [gpu#] [gt_file]"
		print "\tnetwork is the deploy.prototxt file"
		print "\tweights is the weights.caffemodel file"
		print "\tin_image is the input image to be binarized"
		print "\tout_prefix is a prefix where the output images will be written"
		print "\tgpu is an integer device ID to run networks on the specified GPU.  If ommitted, CPU mode is used"
		exit(1)
	network = sys.argv[1]
	weights = sys.argv[2]
	in_image = sys.argv[3]
	out_prefix = sys.argv[4]

	# use gpu if specified
	try:
		gpu = int(sys.argv[5])
		if gpu >= 0:
			caffe.set_mode_gpu()
			caffe.set_device(gpu)
	except:
		caffe.set_mode_cpu()

	main(network, weights, in_image, out_prefix)
	
