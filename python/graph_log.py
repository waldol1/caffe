
import os
import traceback
import argparse
import matplotlib
matplotlib.use("AGG")
import matplotlib.pyplot as plt
plt.ioff()
import numpy as np
import collections
import json


_dd_l = lambda: collections.defaultdict(list)
_ddd_l = lambda: collections.defaultdict(_dd_l)
_dddd_l = lambda: collections.defaultdict(_ddd_l)

def parse_log_file(args):
	sequences = {
				"Test_Losses": _dd_l(),
				"Train_Losses": _dd_l(),
				"LR": [],
				"Test_Layer_Activations": _dddd_l(),
				"Train_Layer_Activations": _ddd_l(),
				"Train_Layer_Gradients": _ddd_l(),
				"Network_Parameters": _ddd_l(),
				"Network_Parameter_Gradients": _ddd_l(),
				"Network_Parameter_Updates": _ddd_l(),
				"Network_Parameter_Norms": _dd_l()
	}
	cur_iter = -1
	debug_state = "Train"
	for ln,line in enumerate(open(args.log_file, 'r').readlines(), start=1):
		line = line.rstrip()
		tokens = line.split()
		try:
			if "Iteration" in tokens:
				pos = tokens.index("Iteration")
				cur_iter = int(tokens[pos+1].rstrip(','))
				if tokens[pos+2] == "Testing":
					debug_state = "Test"
				if tokens[pos+2] == "loss":
					sequences["Train_Losses"]["overall"].append( (cur_iter, float(tokens[pos+4])) )
			if cur_iter < 0:
				continue
			if tokens[4] == "Test" and tokens[5] == "loss:":
				sequences["Test_Losses"]["overall"].append( (cur_iter, float(tokens[6])) )
			if (len(tokens) > 10 and tokens[4] in ["Train", "Test"] and 
					tokens[5] == "net" and tokens[6] == "output"):
				loss_name = tokens[8].replace('/', '-')
				assert tokens[9] == '='
				raw_loss_val = float(tokens[10])
				sequences["%s_Losses" % tokens[4]]["%s_raw" % loss_name].append( (cur_iter, raw_loss_val) )
				if len(tokens) > 14:
					scaled_loss_val = float(tokens[14])
					sequences["%s_Losses" % tokens[4]]["%s_scaled" % loss_name].append( (cur_iter, scaled_loss_val) )
				debug_state = "Train"
			if len(tokens) > 8 and tokens[6] == 'lr':
				lr = float(tokens[8])
				sequences['LR'].append( (cur_iter, lr) )

			if len(tokens) > 11 and tokens[4] == "[Forward]":
				layer_name = tokens[6].rstrip(",").replace('/', '-')
				if tokens[7] == "top":
					blob_name = tokens[9].replace('/', '-')
					aabs = float(tokens[11])
					if debug_state == "Test":
						sequences['Test_Layer_Activations'][layer_name][blob_name][cur_iter].append(aabs)
					else:
						sequences['Train_Layer_Activations'][layer_name][blob_name].append( (cur_iter, aabs) )
				elif tokens[7] == "param" and debug_state == "Train":
					param_num = tokens[9].replace('/', '-')
					aabs = float(tokens[11])
					sequences['Network_Parameters'][layer_name][param_num].append( (cur_iter, aabs) )

			if len(tokens) > 11 and tokens[4] == "[Backward]":
				if tokens[5] == "All":
					data_l1_norm = float(tokens[13].strip("(,"))
					diff_l1_norm = float(tokens[14].strip(");"))
					data_l2_norm = float(tokens[18].strip("(,"))
					diff_l2_norm = float(tokens[19].strip(")"))

					sequences['Network_Parameter_Norms']["L1_Parameters"].append( (cur_iter, data_l1_norm) )
					sequences['Network_Parameter_Norms']["L1_Gradients"].append( (cur_iter, diff_l1_norm) )
					sequences['Network_Parameter_Norms']["L2_Parameters"].append( (cur_iter, data_l2_norm) )
					sequences['Network_Parameter_Norms']["L2_Gradients"].append( (cur_iter, diff_l2_norm) )
				else:
					layer_name = tokens[6].rstrip(",")
					if tokens[7] == "bottom":
						blob_name = tokens[9].replace('/', '-')
						aabs = float(tokens[11])
						sequences['Train_Layer_Gradients'][layer_name][param_num].append( (cur_iter, aabs) )
					else:
						param_num = tokens[9].replace('/', '-')
						aabs = float(tokens[11])
						sequences['Network_Parameter_Gradients'][layer_name][param_num].append( (cur_iter, aabs) )
					
			if len(tokens) > 12 and tokens[4] == "[Update]":
				layer_name = tokens[6].rstrip(",").replace('/', '-')
				param_num = tokens[8].replace('/', '-')
				aabs = float(tokens[12])
				sequences['Network_Parameter_Updates'][layer_name][param_num].append( (cur_iter, aabs) )
		except Exception as e:
			print line
			print list(enumerate(tokens))
			print e
			print traceback.format_exc()

	return sequences

def plot(lists, out_file, title="", xlabel="", ylabel=""):
	_max = -1000000
	_min = 10000000
	graph = False
	for name in lists:
		print name
		l = lists[name]
		graph |= bool(l)
		if l:
			while len(l) > 18000:
				# downsample for plotting
				l = l[::2]
			x, y = zip(*l)
			plt.plot(x, y, label=name)
			_max = max(_max, max(map(abs, y)))
			_min = min(_min, min(map(abs, y)))
	if graph:
		plt.xlabel(xlabel)
		plt.xlabel(ylabel)
		plt.title(title)
		if len(lists) > 1:
			plt.legend()

		if _min and abs(_max / _min) > 50:
			plt.yscale("symlog", basey=10, linthreshy=_min*3)
			base = out_file[:-4]
			plt.savefig(base + "_logscale.png")
			plt.yscale("linear")

		plt.savefig(out_file)
	plt.clf()
	
def plot_per_layer_graphs(d, out_dir, label):
	try:
		os.makedirs(out_dir)
	except:
		pass
	for layer in d:
		layer_d = d[layer]
		for blob in layer_d:
			blob_tups = layer_d[blob]
			out_file = os.path.join(out_dir, "layer_%s_blob_%s.png" % (layer, blob))
			if blob_tups:
				plot({"blob %s" % label : blob_tups}, out_file, "Layer %s: blob %s %s" % (layer, blob, label),
					"Iterations", label)
			

def main(args):
	sequences = parse_log_file(args)
	try:
		os.makedirs(args.out_dir)
	except:
		pass
	#print json.dumps(sequences, indent=4)
	plot({"LR" : sequences['LR']}, os.path.join(args.out_dir, "lr.png"), "Learning Rate",
		"Iterations", "Learning Rate")
	for phase in ["Train", "Test"]:
		d = sequences["%s_Losses" % phase]
		for loss_name, tups in d.items():
			print phase, loss_name
			plot({loss_name: tups}, os.path.join(args.out_dir, "%s_loss_%s.png" % (phase, loss_name)),
				"%s loss: %s" % (phase, loss_name), "Iterations", loss_name)
			if phase == "Train" and loss_name in sequences["Test_Losses"]:
				test_tups = sequences["Test_Losses"][loss_name]
				plot({"Train %s" % loss_name : tups, "Test %s" % loss_name: test_tups}, 
					os.path.join(args.out_dir, "Both_loss_%s.png" % loss_name),
					"loss: %s" % loss_name, "Iterations", loss_name)
	plot_per_layer_graphs(sequences["Train_Layer_Activations"], os.path.join(args.out_dir, "Train_Layer_Activations"), "activation")
	plot_per_layer_graphs(sequences["Train_Layer_Gradients"], os.path.join(args.out_dir, "Train_Layer_Gradients"), "gradients")
	plot_per_layer_graphs(sequences["Network_Parameters"], os.path.join(args.out_dir, "Network_Parameters"), "values")
	plot_per_layer_graphs(sequences["Network_Parameter_Gradients"], os.path.join(args.out_dir, "Network_Parameters_Gradients"), "gradients")
	plot_per_layer_graphs(sequences["Network_Parameter_Updates"], os.path.join(args.out_dir, "Network_Parameter_Updates"), "deltas")
	plot({"L1_Parameters" : sequences["Network_Parameter_Norms"]["L1_Parameters"],
		"L2_Parameters" : sequences["Network_Parameter_Norms"]["L2_Parameters"]}, os.path.join(args.out_dir, "Param_Norms.png"),
		"Parameter Norms", "Iterations", "Norm")
	plot({"L1_Gradients" : sequences["Network_Parameter_Norms"]["L1_Gradients"],
		"L2_Gradients" : sequences["Network_Parameter_Norms"]["L2_Gradients"]}, os.path.join(args.out_dir, "Param_Gradient_Norms.png"),
		"Parameter Gradient Norms", "Iterations", "Norm")

	# fix Test Layer Activations to get an average over all the batches
	for layer in sequences['Test_Layer_Activations']:
		for blob in sequences['Test_Layer_Activations'][layer]:
			for _iter in list(sequences['Test_Layer_Activations'][layer][blob].keys()):
				l = sequences['Test_Layer_Activations'][layer][blob][_iter]
				if l:
					avg = sum(l) / len(l)
					sequences['Test_Layer_Activations'][layer][blob][_iter] = avg
				else:
					del sequences['Test_Layer_Activations'][layer][blob][_iter]
			sequences['Test_Layer_Activations'][layer][blob] = [ (x, y) for x, y in 
				sequences['Test_Layer_Activations'][layer][blob].items() ]

	plot_per_layer_graphs(sequences["Test_Layer_Activations"], os.path.join(args.out_dir, "Test_Layer_Activations"), "activation")

	if 'accuracy_raw' in sequences['Test_Losses']:
		accuracies = sequences['Test_Losses']['accuracy_raw']
		accuracies.sort(key=lambda tup: tup[1])
		tup = accuracies[-1]
		print tup
		print tup[0]


	if 'precision_raw' in sequences['Test_Losses'] and 'recall_raw' in sequences['Test_Losses']:
		precisions = sequences['Test_Losses']['precision_raw']
		recalls = sequences['Test_Losses']['recall_raw']
		f_measures = list()
		for precision, recall in zip(precisions, recalls):
			_iter, p = precision
			_iter, r = recall
			try:
				f = 2 * p * r / (p + r)
			except:
				f = 0
			f_measures.append( (_iter, f) )
		f_measures.sort(key=lambda tup: tup[1])
		tup = f_measures[-1]
		print "f_measure", tup
		print tup[0]

	if 'weighted_fmeasure_loss_raw' in sequences['Test_Losses']:
		fmeasures = sequences['Test_Losses']['weighted_fmeasure_loss_raw']
		fmeasures.sort(key=lambda tup: tup[1])
		tup = fmeasures[0]  # lower is better
		print tup
		print tup[0]


def get_args():
	parser = argparse.ArgumentParser(description="Creates an LMDB of DocumentDatums")
	parser.add_argument('log_file', type=str,
						help='log file of caffe run')
	parser.add_argument('out_dir', type=str,
						help='out directory.  Created if it does not already exist')
	args = parser.parse_args()
	return args
	

if __name__ == "__main__":
	args = get_args()
	main(args)

