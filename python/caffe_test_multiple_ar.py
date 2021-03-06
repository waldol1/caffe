
import os
import sys
import caffe
import cv2
import math
import lmdb
import random
import argparse
import numpy as np
import caffe.proto.caffe_pb2
import scipy.ndimage
import traceback

def init_caffe(args):
	if args.gpu >= 0:
		caffe.set_mode_gpu()
		caffe.set_device(args.gpu)
	else:
		caffe.set_mode_cpu()

	caffenet = caffe.Net(args.caffe_model, args.caffe_weights, caffe.TEST)
	return caffenet

def apply_elastic_deformation(im, tokens):
	sigma, alpha, seed = float(tokens[1]), float(tokens[2]), int(tokens[3])
	np.random.seed(seed)

	displacement_x = np.random.uniform(-1 * alpha, alpha, im.shape[:2])
	displacement_y = np.random.uniform(-1 * alpha, alpha, im.shape[:2])

	displacement_x = scipy.ndimage.gaussian_filter(displacement_x, sigma, truncate=2)
	displacement_y = scipy.ndimage.gaussian_filter(displacement_y, sigma, truncate=2)

	coords_y = np.asarray( [ [y] * im.shape[1] for y in xrange(im.shape[0]) ])
	coords_y = np.clip(coords_y + displacement_y, 0, im.shape[0])

	coords_x = np.transpose(np.asarray( [ [x] * im.shape[0] for x in xrange(im.shape[1]) ] ))
	coords_x = np.clip(coords_x + displacement_x, 0, im.shape[1])

	# the backwards mapping function, which assures that all coords are in
	# the range of the input
	if im.ndim == 3:
		coords_y = coords_y[:,:,np.newaxis]
		coords_y = np.concatenate(im.shape[2] * [coords_y], axis=2)[np.newaxis,:,:,:]

		coords_x = coords_x[:,:,np.newaxis]
		coords_x = np.concatenate(im.shape[2] * [coords_x], axis=2)[np.newaxis,:,:,:]

		coords_d = np.zeros_like(coords_x)
		for x in xrange(im.shape[2]):
			coords_d[:,:,:,x] = x
		coords = np.concatenate( (coords_y, coords_x, coords_d), axis=0)
	else:
		coords = np.concatenate( (coords_y[np.newaxis,:,:], coords_x[np.newaxis,:,:]), axis=0)

	## first order spline interpoloation (bilinear?) using the backwards mapping
	output = scipy.ndimage.map_coordinates(im, coords, order=1, mode='reflect')

	return output



# "crop y x height width"
def apply_crop(im, tokens):
	y, x = int(tokens[1]), int(tokens[2])
	height, width = int(tokens[3]), int(tokens[4])
	if y >= im.shape[0] or x >= im.shape[1]:
		print "Invalid crop: (y,x) outside image bounds (%r with %r)" % (im.shape, tokens)
		exit(1)
	if (y < 0 and y + height >= 0) or (x < 0 and x + width >= 0):
		print "Invalid crop: negative indexing has wrap around (%r with %r)" % (im.shape, tokens)
		exit(1)
	if (height > im.shape[0]) or (width > im.shape[1]):
		print "Invalid crop: crop dims larger than image (%r with %r)" % (im.shape, tokens)
		exit(1)
	if (y + height > im.shape[0]) or (x + width > im.shape[1]):
		print "Invalid crop: crop goes off edge of image (%r with %r)" % (im.shape, tokens)
		exit(1)
		
	return im[y:y+height,x:x+width]

def apply_dense_crop(im, tokens):
	height, width, = int(tokens[1]), int(tokens[2])
	y_stride, x_stride, = int(tokens[3]), int(tokens[4])
	if (height > im.shape[0]) or (width > im.shape[1]):
		print "Invalid crop: crop dims larger than image (%r with %r)" % (im.shape, tokens)
		exit(1)
	ims = list()
	y = 0
	while (y + height) <= im.shape[0]:
		x = 0
		while (x + width) <= im.shape[1]:
			ims.append(im[y:y+height,x:x+width])
			x += x_stride
		y += y_stride
	
	return ims

def apply_rand_crop(im, tokens):
	height, width = int(tokens[1]), int(tokens[2])
	if (height > im.shape[0]) or (width > im.shape[1]):
		print "Invalid crop: crop dims larger than image (%r with %r)" % (im.shape, tokens)
		exit(1)

	y = random.randint(0, im.shape[0] - height)
	x = random.randint(0, im.shape[1] - width)
	return im[y:y+height,x:x+width]

# "resize height width"
def apply_resize(im, tokens):
	size = int(tokens[2]), int(tokens[1])
	return cv2.resize(im, size)

# "mirror {h,v,hv}"
def apply_mirror(im, tokens):
	if tokens[1] == 'h':
		return cv2.flip(im, 0)
	elif tokens[1] == 'v':
		return cv2.flip(im, 1)
	elif tokens[1] == 'hv':
		return cv2.flip(im, -1)
	else:
		print "Unrecongized mirror operation %r" % tokens
		exit(1)

def apply_color_jitter(im, tokens):
	sigma, seed = float(tokens[1]), int(tokens[2])
	np.random.seed(seed)
	im = im.astype(int)  # protect against over-flow wrapping
	if im.shape == 2:
		im = im + int(np.random.normal(0, sigma))
	else:
		for c in xrange(im.shape[2]):
			im[:,:,c] = im[:,:,c] + int(np.random.normal(0, sigma))
	
	# truncate back to image range
	im = np.clip(im, 0, 255)
	im = im.astype(np.uint8) 
	return im

# "guassnoise sigma seed"
def apply_gaussnoise(im, tokens):
	sigma, seed = float(tokens[1]), int(tokens[2])
	np.random.seed(seed)
	noise = np.random.normal(0, sigma, im.shape[:2])
	if len(im.shape) == 2:
		im = (im + noise)
	else:
		im = im + noise[:,:,np.newaxis]
	im = np.clip(im, 0, 255)
	im = im.astype(np.uint8)
	return im

# "rotate degree"
def apply_rotation(im, tokens):
	degree = float(tokens[1])
	center = (im.shape[0] / 2, im.shape[1] / 2)
	rot_mat = cv2.getRotationMatrix2D(center, degree, 1.0)
	return cv2.warpAffine(im, rot_mat, im.shape[:2], flags=cv2.INTER_LINEAR)

# "blur sigma"
def apply_blur(im, tokens):
	sigma = float(tokens[1])
	size = int(sigma * 4 + .999)
	if size % 2 == 0:
		size += 1
	return cv2.GaussianBlur(im, (size, size), sigma)
	
# "unsharpmask sigma amount"
def apply_unsharpmask(im, tokens):
	blurred = np.atleast_3d(apply_blur(im, tokens))
	amount = float(tokens[2])
	sharp = (1 + amount) * im + (-amount * blurred)
	sharp = np.clip(sharp, 0, 255)
	return sharp

# "shear degree {h,v}"
def apply_shear(im, tokens):
	degree = float(tokens[1])
	radians = math.tan(degree * math.pi / 180)
	shear_mat = np.array([ [1, 0, 0], [0, 1, 0] ], dtype=np.float)
	if tokens[2] == 'h':
		shear_mat[0,1] = radians
	elif tokens[2] == 'v':
		shear_mat[1,0] = radians
	else:
		print "Invalid shear type: %r" % tokens
	return cv2.warpAffine(im, shear_mat, im.shape[:2], flags=cv2.INTER_LINEAR)

# "perspective dy1 dx1 dy2 dx2 dy3 dx3 dy4 dx4"
def apply_perspective(im, tokens):
	pts1 = np.array([[0,0],[1,0],[1,1],[0,1]], dtype=np.float32)
	pts2 = np.array([[0 + float(tokens[1]) ,0 + float(tokens[2])],
					   [1 + float(tokens[3]) ,0 + float(tokens[4])],
					   [1 + float(tokens[5]) ,1 + float(tokens[6])],
					   [0 + float(tokens[7]) ,1 + float(tokens[8])]
					   ], dtype=np.float32)
	M = cv2.getPerspectiveTransform(pts1,pts2)
	return cv2.warpPerspective(im, M, im.shape[:2])

def apply_transform(im, transform_str):
	tokens = transform_str.split()
	if tokens[0] == 'crop':
		return apply_crop(im, tokens)
	if tokens[0] == 'densecrop':
		return apply_dense_crop(im, tokens)
	if tokens[0] == 'randcrop':
		return apply_rand_crop(im, tokens)
	elif tokens[0] == 'resize':
		return apply_resize(im, tokens)
	elif tokens[0] == 'mirror':
		return apply_mirror(im, tokens)
	elif tokens[0] == 'gaussnoise':
		return apply_gaussnoise(im, tokens)
	elif tokens[0] == 'rotation':
		return apply_rotation(im, tokens)
	elif tokens[0] == 'blur':
		return apply_blur(im, tokens)
	elif tokens[0] == 'unsharpmask' or tokens[0] == 'unsharp':
		return apply_unsharpmask(im, tokens)
	elif tokens[0] == 'shear':
		return apply_shear(im, tokens)
	elif tokens[0] == 'perspective':
		return apply_perspective(im, tokens)
	elif tokens[0] == 'color_jitter':
		return apply_color_jitter(im, tokens)
	elif tokens[0] == 'elastic':
		return apply_elastic_deformation(im, tokens)
	elif tokens[0] == 'none':
		return im
	else:
		print "Unknown transform: %r" % transform_str
		exit(1)

# all transforms must yield images of the same dimensions
def apply_transforms(im, multi_transform_str):
	transform_strs = multi_transform_str.split(';')
	for ts in transform_strs:
		im = apply_transform(im, ts)
	return im

def apply_all_transforms(im, transform_strs):
	ims = list()
	for ts in transform_strs:
		im_out = apply_transforms(im, ts)
		if type(im_out) is list:
			ims.extend(im_out)
		else:
			ims.append(im_out)
	return ims

def get_transforms(args):
	transforms = list()
	if args.transform_file:
		transforms = map(lambda s: s.rstrip().lower(), open(args.transform_file, 'r').readlines())
	if not transforms:
		transforms.append("none")
	transforms = filter(lambda s: not s.startswith("#"), transforms)
	fixed_transforms = not any(map(lambda s: s.startswith("densecrop"), transforms))
	return transforms, fixed_transforms

def get_image(dd_serialized, slice_idx, args):
	doc_datum = caffe.proto.caffe_pb2.DocumentDatum()
	doc_datum.ParseFromString(dd_serialized)	

	channel_tokens = args.channels.split(args.delimiter)
	channel_idx = min(slice_idx, len(channel_tokens)-1)
	num_channels = int(channel_tokens[channel_idx])

	nparr = np.fromstring(doc_datum.image.data, np.uint8)
	#print len(doc_datum.image.data)
	im = cv2.imdecode(nparr, int(num_channels == 3) )
	if im.ndim == 2:
		# explicit single channel to match dimensions of color
		im = im[:,:,np.newaxis]
	label = doc_datum.dbid
	return im, label

# currently only does mean and shift
# transposition is handled by predict() so intermediate augmentations can take place
def scale_shift_im(im, slice_idx, args):

	# find the correct mean values.  
	means_tokens = args.means.split(args.delimiter)
	mean_idx = min(slice_idx, len(means_tokens) - 1)
	mean_vals = np.asarray(map(int, means_tokens[mean_idx].split(',')))

	# find the correct scale value
	scale_tokens = args.scales.split(args.delimiter)
	scale_idx = min(slice_idx, len(scale_tokens) - 1)
	scale_val = float(scale_tokens[scale_idx]) 

	preprocessed_im = scale_val * (im - mean_vals)
	return preprocessed_im

def set_transform_weights(args):
	# check if transform weights need to be done
	if args.tune_lmdbs == "":
		# no lmdb is provided for tuning the weights
		return None
	transforms, fixed_transforms = get_transforms(args)
	if not fixed_transforms:
		# number of transforms varies by image, so no fixed set of weights
		return None

	try:
		caffenet = init_caffe(args)
		tune_dbs = open_dbs(args.tune_lmdbs.split(args.delimiter))

		weights = np.zeros(shape=(len(transforms),))
		num_total = 0
		done = False
		while not done:
			if num_total % args.print_count == 0:
				print "Tuned %d images" % num_total
			num_total += 1

			# get the per-transform vote for the correct label
			ims, label = prepare_images(tune_dbs, transforms, args)
			votes = get_vote_for_label(ims, caffenet, label, args)
			weights += votes

			# check stopping criteria
			done = (num_total == args.max_images)
			for env, txn, cursor in tune_dbs:
				has_next = cursor.next() 
				done |= (not has_next) # set done if there are no more elements

		normalized = (weights / num_total)[:,np.newaxis]
		return normalized
	except Exception as e:
		traceback.print_exc()
		print e
		raise
	finally:
		close_dbs(tune_dbs)

def get_vote_for_label(ims, caffenet, label, args):
	# batch up all transforms at once
	all_outputs = fprop(caffenet, ims, args.batch_size)

	if args.hard_weights:
		# use 1/0 right or not
		predictions = np.argmax(all_outputs, axis=1)
		accuracy = np.zeros(shape=(len(ims),))
		accuracy[predictions == label] = 1
		return accuracy
	else:
		# use the probability of the correct label
		return all_outputs[:, label]


def fprop(caffenet, ims, batchsize=64):
	# batch up all transforms at once
	idx = 0
	responses = list()
	while idx < len(ims):
		sub_ims = ims[idx:idx+batchsize]
		caffenet.blobs["data"].reshape(len(sub_ims), ims[0].shape[2], ims[0].shape[0], ims[0].shape[1]) 
		for x, im in enumerate(sub_ims):
			transposed = np.transpose(im, [2,0,1])
			transposed = transposed[np.newaxis, :, :, :]
			caffenet.blobs["data"].data[x,:,:,:] = transposed
		idx += batchsize

		# propagate on batch
		caffenet.forward()
		responses.append(np.copy(caffenet.blobs["prob"].data))
	return np.concatenate(responses, axis=0)
	

def predict(ims, caffenet, args, weights=None):
	# set up transform weights
	if weights is None:
		weights = np.array([1] * len(ims))
		weights = weights[:,np.newaxis]

	all_outputs = fprop(caffenet, ims, args.batch_size)

	all_predictions = np.argmax(all_outputs, axis=1)
	weighted_outputs = all_outputs * weights
	mean_outputs = np.sum(weighted_outputs, axis=0)
	label = np.argmax(mean_outputs)
	return label, all_predictions

def open_dbs(db_paths):
	dbs = list()
	for path in db_paths:
		env = lmdb.open(path, readonly=True, map_size=int(2 ** 42))
		txn = env.begin(write=False)
		cursor = txn.cursor()
		cursor.first()
		dbs.append( (env, txn, cursor) )
	return dbs

def close_dbs(dbs):
	for env, txn, cursor in dbs:
		txn.abort()
		env.close()

def log(args, s, newline=True):
	print s
	if args.log_file:
		if not hasattr(args, 'log'):
			args.log = open(args.log_file, 'w')
		if newline:
			args.log.write("%s\n" % s)
		else:
			args.log.write(s)


# slice index refers to which LMDB the partial image came from
# transform index refers to which transforms of the image
def prepare_images(test_dbs, transforms, args):
	ims_slice_transforms = list()
	labels = list()
	keys = list()

	# apply the transformations to every slice of the image independently
	for slice_idx, entry in enumerate(test_dbs):
		env, txn, cursor = entry

		im_slice, label_slice = get_image(cursor.value(), slice_idx, args)
		transformed_slices = apply_all_transforms(im_slice, transforms)
		for transform_idx in xrange(len(transformed_slices)):
			transformed_slices[transform_idx] = scale_shift_im(transformed_slices[transform_idx], slice_idx, args)

		ims_slice_transforms.append(transformed_slices)
		labels.append(label_slice)
		keys.append(cursor.key())

	# check that all keys match
	key = keys[0]
	for slice_idx, _key in enumerate(keys):
		if _key != key:
			log(args, "WARNING!, keys differ %s vs %s for slices %d and %d" % (key, _key, 0, slice_idx))

	
	# check that all labels match
	label = labels[0]
	for slice_idx, _label in enumerate(labels):
		if _label != label:
			log(args, "WARNING!, key %s has differing labels: %d vs %d for slices %d and %d" % (key, label, _label, 0, slice_idx))

	# stack each set of slices (along channels) into a single numpy array
	num_transforms = len(ims_slice_transforms[0])
	num_slices = len(ims_slice_transforms)
	ims = list()
	for transform_idx in xrange(num_transforms):
		im_slices = list()
		for slice_idx in xrange(num_slices):
			im_slice = ims_slice_transforms[slice_idx][transform_idx]
			im_slices.append(np.atleast_3d(im_slice))
		whole_im = np.concatenate(im_slices, axis=2) # append along channels
		ims.append(whole_im)

	return ims, label


def main(args):
	log(args, str(sys.argv))

	# load transforms from file
	log(args, "Loading transforms")
	transforms, fixed_transforms = get_transforms(args)
	log(args, "Fixed Transforms: %s" % str(fixed_transforms))

	# get per-transform weights.  Can be none if transforms produce variable numbers of images, or
	# no lmdb is provided to tune the weights
	log(args, "Setting the transform weights...")
	weights = set_transform_weights(args) 
	weight_str = np.array_str(weights, max_line_width=80, precision=4) if weights is not None else str(weights)
	log(args, "Weights: %s" % weight_str)

	log(args, "Initializing network for testing")
	caffenet = init_caffe(args)
	log(args, "Opening test lmdbs")
	test_dbs = open_dbs(args.test_lmdbs.split(args.delimiter))

	try:
		# set up the class confusion matrix
		num_output = caffenet.blobs["prob"].data.shape[1]
		conf_mat = np.zeros(shape=(num_output, num_output), dtype=np.int)

		num_total = 0
		num_correct = 0
		all_num_correct = np.zeros(shape=(len(transforms),))
		for test_db in test_dbs:
			done = False
			while not done:
				if num_total % args.print_count == 0:
					print "Processed %d images" % num_total
				num_total += 1

				ims, label = prepare_images([test_db], transforms, args)
				predicted_label, all_predictions = predict(ims, caffenet, args, weights)

				# keep track of correct predictions
				if predicted_label == label:
					num_correct += 1
				conf_mat[label,predicted_label] += 1

				# compute per-transformation accuracy
				if all_predictions.shape[0] == all_num_correct.shape[0]:
					all_num_correct[all_predictions == label] += 1

				# check stopping criteria
				done = (num_total == args.max_images)
				for env, txn, cursor in [test_db]:
					has_next = cursor.next() 
					done |= (not has_next) # set done if there are no more elements

		overall_acc = float(num_correct) / num_total
		transform_accs = all_num_correct / num_total

		log(args, "Done")
		log(args, "Conf Mat:\n %r" % conf_mat)
		log(args, "\nTransform Accuracy:\n %r" % transform_accs)
		log(args, "\nCorrect/Total:\n %r/%r" % (num_correct, num_total))
		log(args, "\nOverall Accuracy: %f" % overall_acc)
	except Exception as e:
		traceback.print_exc()
		print e
		raise
	finally:
		close_dbs(test_dbs)
		if args.log:
			args.log.close()
		

def check_args(args):
	num_tune_lmdbs = 0 if args.tune_lmdbs == "" else len(args.tune_lmdbs.split(args.delimiter))
	num_test_lmdbs = 0 if args.test_lmdbs == "" else len(args.test_lmdbs.split(args.delimiter))
	if num_test_lmdbs == 0:
		raise Exception("No test lmdbs specified");
	if num_tune_lmdbs != 0 and num_tune_lmdbs != num_test_lmdbs:
		raise Exception("Different number of tune and test lmdbs: %d vs %d" % (num_tune_lmdb, num_test_lmdbs))

	num_scales = len(args.scales.split(args.delimiter))
	if num_scales != 1 and num_scales != num_test_lmdbs:
		raise Exception("Different number of test lmdbs and scales: %d vs %d" % (num_test_lmdbs, num_scales))

	num_means = len(args.means.split(args.delimiter))
	if num_means != 1 and num_means != num_test_lmdbs:
		raise Exception("Different number of test lmdbs and means: %d vs %d" % (num_test_lmdbs, num_means))

	num_channels = len(args.channels.split(args.delimiter))
	if num_channels != 1 and num_channels != num_test_lmdbs:
		raise Exception("Different number of test lmdbs and channels: %d vs %d" % (num_test_lmdbs, num_channels))
		
			
def get_args():
	parser = argparse.ArgumentParser(description="Classifies data")
	parser.add_argument("caffe_model", 
				help="The model definition file (e.g. deploy.prototxt)")
	parser.add_argument("caffe_weights", 
				help="The model weight file (e.g. net.caffemodel)")
	parser.add_argument("test_lmdbs", 
				help="LMDBs of test images (encoded DocDatums), files separated with ;")

	parser.add_argument("-m", "--means", type=str, default="",
				help="Optional mean values per the channel (e.g. 127 for grayscale or 182,192,112 for BGR)")
	parser.add_argument("--gpu", type=int, default=-1,
				help="GPU to use for running the network")
	parser.add_argument('-c', '--channels', default="0", type=str,
				help='Number of channels to take from each slice')
	parser.add_argument("-a", "--scales", type=str, default=str(1.0 / 255),
				help="Optional scale factor")
	parser.add_argument("-t", "--transform_file", type=str, default="",
				help="File containing transformations to do")
	parser.add_argument("-l", "--tune-lmdbs", type=str, default="",
				help="Tune the weighted averaging to minmize CE loss on this data")
	parser.add_argument("-f", "--log-file", type=str, default="",
				help="Log File")
	parser.add_argument("-z", "--hard-weights", default=False, action="store_true",
				help="Compute Transform weights using hard assignment")
	parser.add_argument("--print-count", default=1000, type=int, 
				help="Print every print-count images processed")
	parser.add_argument("--max-images", default=40000, type=int, 
				help="Max number of images for processing or tuning")
	parser.add_argument("-d", "--delimiter", default=':', type=str, 
				help="Delimiter used for indicating multiple image slice parameters")
	parser.add_argument("-b", "--batch-size", default=64, type=int, 
				help="Max number of transforms in single batch per original image")

	args = parser.parse_args()

	#check_args(args)
	return args
	

if __name__ == "__main__":
	args = get_args()
	main(args)

