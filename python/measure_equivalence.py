
import os
import re
import sys
import caffe  # must come before cv2
import cv2
import h5py
import math
import lmdb
import errno
import shutil
import random
import pprint
import tempfile
import argparse
import traceback
import scipy.stats
import numpy as np
import scipy.ndimage
import caffe.proto.caffe_pb2
from caffe import layers as L, params as P
from utils import get_transforms, apply_all_transforms, safe_mkdir

#LOSS_TYPES = ['l2', 'ce_soft', 'ce_hard']
LOSS_TYPES = ['l2']
#MODEL_TYPES = ['linear', 'mlp']
MODEL_TYPES = ['linear']

def setup_scratch_space(args):
	#safe_mkdir("./tmp")
	#args.tmp_dir = "./tmp"
	args.tmp_dir = tempfile.mkdtemp()
	log(args, "Using tmp space: " + args.tmp_dir)
	args.train_file = os.path.join(args.tmp_dir, "train_val.prototxt")
	args.train_db = os.path.join(args.tmp_dir, "train.h5")
	args.train_db_list = os.path.join(args.tmp_dir, "train_list.txt")
	with open(args.train_db_list, 'w') as f:
		f.write('%s\n' % args.train_db)

	args.test_db = os.path.join(args.tmp_dir, "test.h5")
	args.test_db_list = os.path.join(args.tmp_dir, "test_list.txt")
	with open(args.test_db_list, 'w') as f:
		f.write('%s\n' % args.test_db)
	args.solver_file = os.path.join(args.tmp_dir, "solver.prototxt")


def cleanup_scratch_space(args):
	shutil.rmtree(args.tmp_dir)


def equivalence_proto(args, num_features, num_classes, loss='l2', mlp=False):
	if loss == 'l2':
		ce_hard_loss_weight = 0
		ce_soft_loss_weight = 0
		l2_loss_weight = 1
	elif loss == 'ce_hard':
		ce_hard_loss_weight = 0.75
		ce_soft_loss_weight = 0
		l2_loss_weight = 0.25
	else:
		ce_hard_loss_weight = 0
		ce_soft_loss_weight = 0.75
		l2_loss_weight = 0.25

	n = caffe.NetSpec()

	n.input_features, n.target_features, n.target_output_probs, n.labels, n.idx = L.HDF5Data(
			batch_size=args.train_batch_size, source=args.train_db_list, ntop=5, include=dict(phase=caffe.TRAIN))

	n.input_features_scale, n.target_features_scale, n.reconstructed_features_scale = L.HDF5Data(
			batch_size=args.train_batch_size, source=args.train_db_list, ntop=3, include=dict(phase=caffe.TRAIN))

	n.VAL_input_features, n.VAL_target_features, n.VAL_target_output_probs, n.VAL_labels, n.VAL_idx = L.HDF5Data(
		batch_size=1, source=args.test_db_list, ntop=5, include=dict(phase=caffe.TEST))

	n.VAL_input_features_scale, n.VAL_target_features_scale, n.VAL_reconstructed_features_scale = L.HDF5Data(
		batch_size=1, source=args.test_db_list, ntop=3, include=dict(phase=caffe.TEST))

	# scale inputs and targets so each neuron has equal importance in weight decay and loss
	n.scaled_input_features = L.Scale(n.input_features, n.input_features_scale, axis=0)
	n.scaled_target_features = L.Scale(n.target_features, n.target_features_scale, axis=0)

	if mlp:
		n.prev = L.InnerProduct(n.scaled_input_features, num_output=args.hidden_size, name='mlp_hidden',
			weight_filler={'type': 'msra'})
		n.prev = L.TanH(n.prev, in_place=True)

		n.prev = L.InnerProduct(n.prev, num_output=num_features, name='linear',
			weight_filler={'type': 'msra'})
	else:
		n.prev = L.InnerProduct(n.scaled_input_features, num_output=num_features, name='linear',
			weight_filler={'type': 'msra'})


	# caffe will automatically insert split layers when two or more layers have the same bottom, but
	# in so doing, it mangles the name.  By explicitly doing the split, we control the names so that 
	# the blob values can be accessed by the names given here
	#n.prev = n.scaled_input_features
	n.scaled_reconstruction = L.ReLU(n.prev, name='scaled_reconstruction')  # assumes that target_features are rectified
	n.scaled_reconstruction1, n.scaled_reconstruction2 = L.Split(n.scaled_reconstruction, ntop=2)  
	n.reconstruction_loss = L.EuclideanLoss(n.scaled_reconstruction1, n.scaled_target_features, name="reconstruction_loss",
				loss_weight=l2_loss_weight, loss_param=dict(normalize=True)) 

	
	# rescale to the original maginitudes so the reconstructions are compatible with the pretrained classifier
	n.reconstruction = L.Scale(n.scaled_reconstruction2, n.reconstructed_features_scale, name='reconstruction', axis=0)

	# now finish the computation of the rest of the network
	# hard coded for measuring equivariance of last hidden layers
	n.classify = L.InnerProduct(n.reconstruction, num_output=num_classes, name="classify",
		param=[{'lr_mult':0, 'decay_mult':0}, {'lr_mult': 0, 'decay_mult': 0}])  # weights to be fixed to the network's original weights

	n.prob = L.Softmax(n.classify)
	# use the original predicted probs as the targets for CE
	n.ce_loss_soft = L.SoftmaxFullLoss(n.classify, n.target_output_probs, name='ce_loss_soft',
		loss_weight=ce_soft_loss_weight, loss_param=dict(normalize=True))

	# use the labels as the targets for CE
	n.ce_loss_hard = L.SoftmaxWithLoss(n.classify, n.labels, name='ce_loss_hard',
		loss_weight=ce_hard_loss_weight, loss_param=dict(normalize=True))

	# use n.prob to suppress it as an output of the network
	n.accuracy = L.Accuracy(n.prob, n.labels)

	return n.to_proto()


def create_solver(args, num_train_instances, num_test_instances):
	s = caffe.proto.caffe_pb2.SolverParameter()
	s.net = args.train_file

	s.test_interval = num_train_instances / args.train_batch_size / 2
	s.test_iter.append(num_test_instances)
	s.max_iter = num_train_instances / args.train_batch_size * args.max_epochs

	#s.solver_type = caffe.proto.caffe_pb2.SolverType.SGD  # why isn't it working?  Default anyway
	s.momentum = 0.9
	s.weight_decay = 1e-5  # strong weight decay as a prior to the identity mapping
	s.regularization_type = 'L2'
	s.clip_gradients = 5

	s.base_lr = args.learning_rate
	s.monitor_test = True
	s.monitor_test_id = 0
	s.test_compute_loss = True
	s.max_steps_without_improvement = 3
	s.max_periods_without_improvement = 1
	s.gamma = 0.1

	s.solver_mode = caffe.proto.caffe_pb2.SolverParameter.GPU
	s.snapshot = 0  # don't do snapshotting
	s.snapshot_after_train = False
	s.display = 100

	return s
	

def init_model(network_file, weights_file, gpu=0):
	if args.gpu >= 0:
		caffe.set_mode_gpu()
		caffe.set_device(args.gpu)
	else:
		caffe.set_mode_cpu()

	model = caffe.Net(network_file, weights_file, caffe.TEST)
	return model


def log(args, s, newline=True):
	print s
	if args.log_file:
		if not hasattr(args, 'log'):
			args.log = open(args.log_file, 'w')
		if newline:
			args.log.write("%s\n" % s)
		else:
			args.log.write(s)


def measure_avg_l2(a, b):
	total_euclidean_dist = 0
	for idx in xrange(a.shape[0]):
		total_euclidean_dist += np.sqrt(np.sum((a[idx] - b[idx]) ** 2))
	return total_euclidean_dist / a.shape[0]
	

def measure_avg_jsd(a, b):
	total_divergence = 0
	for idx in xrange(a.shape[0]):
		m = 0.5 * (a[idx] + b[idx])
		jsd = 0.5 * (scipy.stats.entropy(a[idx], m) + scipy.stats.entropy(b[idx], m))
		total_divergence += math.sqrt(max(jsd, 0))
	return total_divergence / a.shape[0]

def jsd(a, b):
	m = 0.5 * (a + b)
	d = 0.5 * (scipy.stats.entropy(a, m) + scipy.stats.entropy(b, m))
	return math.sqrt(max(d, 0))


def measure_agreement(a, b):
	return np.sum(a == b) / float(a.shape[0])


def score_model(model, num_instances):

	total_scaled_l2 = 0
	total_l2 = 0
	total_jsd = 0
	num_correct = 0
	num_agree = 0
	num_total = 0

	for idx in xrange(num_instances):
		model.forward()
		arr_idx = model.blobs['idx'].data[0]

		scaled_reconstruction = model.blobs['scaled_reconstruction'].data[0,:]
		scaled_target_features = model.blobs['scaled_target_features'].data[0,:]
		total_scaled_l2 += np.sqrt(np.sum( (scaled_target_features - scaled_reconstruction) ** 2)) / scaled_target_features.shape[0]

		reconstruction = model.blobs['reconstruction'].data[0,:]
		target_features = model.blobs['target_features'].data[0,:]
		total_l2 += np.sqrt(np.sum( (target_features - reconstruction) ** 2)) / target_features.shape[0]

		output_probs = model.blobs['prob'].data[0,:]
		target_output_probs = model.blobs['target_output_probs'].data[0,:]
		total_jsd += jsd(output_probs, target_output_probs)

		classification = np.argmax(model.blobs['prob'].data[0])
		target_classification = np.argmax(target_output_probs)
		label = model.blobs['labels'].data[0]
		if classification == label:
			num_correct += 1
		if classification == target_classification:
			num_agree += 1

		num_total += 1

	num_total = float(num_total)
	metrics = {
	  'avg_scaled_l2': total_scaled_l2 / num_total,
	  'avg_l2': total_l2 / num_total,
	  'avg_jsd': total_jsd / num_total,
	  'accuracy': num_correct / num_total,
	  'agreement': num_correct / num_total
	}

	return metrics
	

def init_empty_metrics():
	d = dict()
	for split in ['train', 'test']:
		d[split] = dict()
		for model_type in MODEL_TYPES:
			d[split][model_type] = dict()
			for loss in LOSS_TYPES:
				d[split][model_type][loss] = dict()
	return d


def train_model(model_type, loss, classifier_weights, classifier_bias, num_train_instances, 
		num_test_instances, num_features, num_classes, args):

	net_param = equivalence_proto(args, num_features, num_classes, loss, model_type == 'mlp')
	with open(args.train_file, 'w') as f:
		f.write(re.sub("VAL_", "", str(net_param)))

	solver_param = create_solver(args, num_train_instances, num_test_instances)
	with open(args.solver_file, 'w') as f:
		f.write(str(solver_param))

	# load the solver and the network files it references
	solver = caffe.get_solver(args.solver_file)

	# fix the classificaiton weights/biases to be the passed in weights/biases
	classify_layer_params = solver.net.params['classify']
	classify_layer_params[0].data[:] = classifier_weights[:]  # data copy, not object reassignment
	classify_layer_params[1].data[:] = classifier_bias[:]

	# apparently necessary, though I thought the weights were shared between the two networks
	classify_layer_params = solver.test_nets[0].params['classify']
	classify_layer_params[0].data[:] = classifier_weights[:]  # data copy, not object reassignment
	classify_layer_params[1].data[:] = classifier_bias[:]

	solver.solve()
	return solver.net, solver.test_nets[0]


def perform_experiment(model_type, loss, classification_weights, classification_bias, num_train_instances, 
		num_test_instances, num_features, num_classes,  args):

	model_train, model_test = train_model(model_type, loss, 
				classification_weights, classification_bias, num_train_instances, 
				num_test_instances, num_features, num_classes, args)
	
	train_metrics = score_model(model_train, num_train_instances)
	test_metrics = score_model(model_test, num_test_instances)

	return train_metrics, test_metrics


def sqrt_second_moment_around_zero(arr):
	second_moment = (1. / arr.shape[0]) * np.sum((arr * arr), axis=0)
	second_moment[second_moment == 0] = 1.  # in case a neuron never fires
	second_moment = second_moment[np.newaxis, :]
	return np.sqrt(second_moment)
	

def write_hdf5(write_db_file, input_db_file, output_db_file, args):
	with h5py.File(write_db_file, 'w') as write_db:
		with h5py.File(input_db_file, 'r') as input_db:
			with h5py.File(output_db_file, 'r') as output_db:
				input_features = np.asarray(input_db[args.blob][:args.max_instances])
				write_db['input_features'] = input_features
				log(args, "Input Features Shape: %s" % str(write_db['input_features'].shape))

				# used to normalize features on the fly
				arr = sqrt_second_moment_around_zero(input_features)
				write_db['input_features_scale'] = 1. / arr
				print "Input_Features scales:"
				print arr[:10]

				target_features = np.asarray(output_db[args.blob][:args.max_instances])
				write_db['target_features'] = target_features
				log(args, "Target Features Shape: %s" % str(write_db['target_features'].shape))
				print "Target Features scales:"
				print arr[:10]

				# used to normalize features on the fly
				arr = sqrt_second_moment_around_zero(target_features)
				write_db['target_features_scale'] = 1. / arr

				# undo the normalization to be on the same scale as the pretrained
				# classification weights
				write_db['reconstructed_features_scale'] = arr

				write_db['target_output_probs'] = np.asarray(output_db['prob'][:args.max_instances])
				log(args, "Target Output Probs Shape: %s" % str(write_db['target_output_probs'].shape))

				write_db['labels'] = np.asarray(output_db['labels'][:args.max_instances])
				log(args, "labels Shape: %s" % str(write_db['labels'].shape))

				write_db['idx'] = np.arange(write_db['labels'].shape[0], dtype=np.float32)

				num_instances, num_features = input_features.shape
				num_classes = output_db['prob'].shape[1]
	return num_instances, num_features, num_classes



def setup_hdf5s(args):
	log(args, "Writing Train HDF5")
	num_train_instances, num_features, num_classes = write_hdf5(args.train_db, 
											args.input_train_hdf5, args.output_train_hdf5, args)

	log(args, "\nWriting Test HDF5")
	num_test_instances, num_features, num_classes = write_hdf5(args.test_db, 
											args.input_test_hdf5, args.output_test_hdf5, args)

	return num_train_instances, num_test_instances, num_features, num_classes
		
		

def main(args):
	log(args, str(args))

	log(args, "Setting up Scratch Space")
	setup_scratch_space(args)

	# pull the classification weights and bias
	log(args, "Loading 'to' model")
	model = init_model(args.network_file, args.weight_file, gpu=args.gpu)

	log(args, "Extracting Classification Weights")
	last_layer_params = model.params.items()[-1][1]
	classification_weights = last_layer_params[0].data
	classification_bias = last_layer_params[1].data

	all_metrics = init_empty_metrics()

	log(args, "Setting up Train/Test DBs")
	num_train_instances, num_test_instances, num_features, num_classes = setup_hdf5s(args)
	log(args, "Num Train Instances: %d" % num_train_instances)
	log(args, "Num Test Instances: %d" % num_test_instances)
	log(args, "Num Features: %d" % num_features)
	log(args, "Num Classes: %d" % num_classes)

	log(args, "Starting on Experiments")
	for model_type in MODEL_TYPES:
		for loss in LOSS_TYPES:
			log(args, "EXPERIMENT %s %s" % (model_type, loss))
			train_metrics, test_metrics = perform_experiment(model_type, loss, 
				classification_weights, classification_bias, num_train_instances, num_test_instances, 
				num_features, num_classes, args)
			all_metrics['train'][model_type][loss] = train_metrics
			all_metrics['test'][model_type][loss] = test_metrics

	with open(args.out_file, 'w') as f:
		f.write(pprint.pformat(all_metrics))

	#cleanup_scratch_space(args)
	log(args, "Exiting...")
		
	if args.log_file:
		args.log.close()


def get_args():
	parser = argparse.ArgumentParser(
		description="Measures invariance of learned representations with respect to the given transforms")
	parser.add_argument("input_train_hdf5", 
				help="HDF5 of vectors used to train equivalence mappings")
	parser.add_argument("input_test_hdf5", 
				help="HDF5 of vectors used to train equivalence mappings")
	parser.add_argument("output_train_hdf5", 
				help="HDF5 of vectors used to train equivalence mappings")
	parser.add_argument("output_test_hdf5", 
				help="HDF5 of vectors used to train equivalence mappings")

	parser.add_argument("network_file", 
				help="Caffe network file for output representation")
	parser.add_argument("weight_file", 
				help="Caffe weights file for output representation")
	parser.add_argument("out_file", type=str,
				help="File to write the output")

	parser.add_argument("-f", "--log-file", type=str, default="",
				help="Log File")

	parser.add_argument("-e", "--max-epochs", type=int, default=10,
				help="Max training epochs for equivalence models")
	parser.add_argument("--max-instances", type=int, default=50000,
				help="Max Instances used to train/test equivalence models")
	parser.add_argument("-l", "--learning-rate", type=float, default=0.01,
				help="Initial Learning rate for equivalence models")
	parser.add_argument("-k", "--hidden-size", type=float, default=2000,
				help="Hidden size for mlp equivalence mappings")
	parser.add_argument("--gpu", type=int, default=0,
				help="GPU to use for running the models")
	parser.add_argument("--blob", type=str, default="InnerProduct2",
				help="Name of db on which to measure equivalence")

	args = parser.parse_args()
	args.train_batch_size = 1

	return args
	

if __name__ == "__main__":
	args = get_args()
	main(args)

