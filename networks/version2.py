# I absolutely hate this sys path stuff
import sys
sys.path.append(sys.path[0] + "/..")

import chess
import os
import numpy as np
import pandas as pd
import tensorflow as tf
import pychess_utils as util
from deepmind_mcts import MCTS

# TODO: Think of another way to encode moves?
# 8x8 choices for source square, 8x8 choices for destination square, 64^2 possible 'moves'
# this means a 64^2=4096 node output layer is required to define a full policy for a given
# position.  That could slow down training significantly...might have to revisit this
# plus 1 more target to train value per position

# Less Verbose Output
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
tf.logging.set_verbosity(tf.logging.ERROR)

class Network:

	DATA_FILE = "/Users/evanmdoyle/Programming/ChessAI/ACZData/self_play.csv"
	PIECE_PREFIXES = ['p_', 'n_', 'b_', 'r_', 'q_', 'k_']
	RESIDUAL_BLOCKS = 10

	def __init__(self):
		self.__nn = tf.estimator.Estimator(model_fn=self.model_fn, params={})
		self.__nn.train(input_fn=self.input_fn(self.DATA_FILE, num_epochs=None, shuffle=True), steps=1)

	def feature_col_names(self):
		# 8x8 board for each piece type (6) for each player (2) plus an indicator of whose turn it is
		feature_columns = []
		for i in range(2):
			for prefix in self.PIECE_PREFIXES:
				for x in range(64):
					# Column naming convention is [color][piece prefix][square number]
					# ex: the column labeled 0p_25 holds a 1 when a black pawn occupies position 25
					feature_columns.append(str(i)+prefix+str(x))
		return feature_columns

	def target_column_names(self):
		# 'probs' here will be a string that must be decoded in model_fn
		return ['probs', 'value']

	def convert(self, uci_move):
		move = chess.Move.from_uci(uci_move)
		return (move.from_square, move.to_square)

	def decode(self, labels):
		new_labels = []
		labels = labels.split('-')
		for label in labels:
			label = label.strip('(').strip(')').split(':')
			label = (self.convert(label[0]), label[1])
			new_labels.append(label)
		return new_labels

	def create_policy(self, labels):
		policy = [float(0) for x in range(4096)]
		for moves, prob in labels:
			policy[(moves[0]*64)+moves[1]] = float(prob)
		return np.array(policy)

	def one_hot(self, value):
		if value:
			return np.array([0, 1])
		else:
			return np.array([1, 0])

	def input_fn(self, data_file, num_epochs, batch_size=30, shuffle=False, num_threads=4):
		feature_cols = self.feature_col_names()
		target_cols = self.target_column_names()
		dataset = pd.read_csv(
			tf.gfile.Open(data_file),
			header=0,
			usecols=feature_cols + target_cols,
			skipinitialspace=True,
			engine="python")
		# Drop NaN entries
		dataset.dropna(how="any", axis=0)

		# Create separate dataframe for y
		policy_labels = dataset.probs.apply(lambda x: self.create_policy(self.decode(x)))
		policy_labels = policy_labels.apply(pd.Series)

		# value_labels = dataset.value.apply(lambda x: self.one_hot(x))
		# value_labels = value_labels.apply(pd.Series)
		value_labels = dataset.value

		dataset.pop('probs')
		dataset.pop('value')

		return tf.estimator.inputs.numpy_input_fn(
			x={"x": np.array(dataset)},
			y=np.array(pd.concat([policy_labels, value_labels], axis=1)),
			batch_size=batch_size,
			num_epochs=num_epochs,
			shuffle=shuffle,
			num_threads=num_threads)

	def custom_conv(self, input_layer, f_height, f_width, in_channels, out_channels, stride=[1,1,1,1], name="conv"):
		with tf.variable_scope(name) as scope:
			# need a filter/kernel with size 3x3, 256 output channels
			kernel = tf.get_variable(
				name+"_filter",
				[f_height,f_width,in_channels,out_channels],
				initializer=tf.truncated_normal_initializer(stddev=5e-2, dtype=tf.float32)
				)

			# now need input in format [30,8,8,12]
			board_image = tf.reshape(input_layer, [-1,8,8,12])

			# convolution!
			conv1 = tf.nn.conv2d(input_layer, kernel, stride, padding='SAME', name=scope.name)
			biases1 = tf.get_variable(name+"_biases", [out_channels], initializer=tf.constant_initializer(0.0))
			pre_activation = tf.nn.bias_add(conv1, biases1)

			return pre_activation

	def custom_batch_norm(self, inputs, training=True, name="norm"):
		with tf.variable_scope(name) as scope:
			norm1 = tf.layers.batch_normalization(inputs=inputs, training=True, name=scope.name)
		return norm1

	def custom_relu(self, inputs, name="relu"):
		with tf.variable_scope(name) as scope:
			relu = tf.nn.relu(inputs, name=scope.name)
		return relu

	def model_fn(self, features, labels, mode, params):
		# Labels need to be split into policy and value
		policy_labels, value_labels = tf.split(labels, [4096, 1], axis=1)

		# Input layer comes from features, which come from input_fn
		input_layer = tf.cast(features["x"], tf.float32)
		board_image = tf.reshape(input_layer, [-1,8,8,12])

		pre_activation = self.custom_conv(board_image, 3, 3, 12, 256, name="conv1")

		norm1 = self.custom_batch_norm(pre_activation, name="norm1")

		relu1 = self.custom_relu(norm1, name="relu1")
		# TODO: Add summaries for Tensorboard here

		curr_input = relu1
		for i in range(self.RESIDUAL_BLOCKS):
			id_str = str(2+i)
			conv_layer = self.custom_conv(curr_input, 3, 3, 256, 256, name="conv"+id_str)
			norm_layer = self.custom_batch_norm(conv_layer, name="norm"+id_str)
			relu_layer = self.custom_relu(norm_layer, name="relu"+id_str)
			conv_layer_2 = self.custom_conv(relu_layer, 3, 3, 256, 256, name="2conv"+id_str)
			norm_layer_2 = self.custom_batch_norm(conv_layer_2, name="2norm"+id_str)
			residual_layer = tf.add(curr_input, norm_layer_2)
			relu_layer_2 = self.custom_relu(residual_layer, name="2relu"+id_str)
			curr_input = relu_layer_2

		residual_tower_out = curr_input

		policy_conv = self.custom_conv(residual_tower_out, 1, 1, 256, 2, name="policy_conv")
		policy_norm = self.custom_batch_norm(policy_conv, name="policy_norm")
		policy_relu = self.custom_relu(policy_norm, name="policy_relu")
		# policy_relu should have shape [batch, 8, 8, 2] so I want [batch, 128]
		policy_relu = tf.reshape(policy_relu, [-1,128])
		policy_output_layer = tf.layers.dense(inputs=policy_relu, units=4096, activation=None)

		value_conv = self.custom_conv(residual_tower_out, 1, 1, 256, 1, name="value_conv")
		value_norm = self.custom_batch_norm(value_conv, name="value_norm")
		value_relu = self.custom_relu(value_norm, name="value_relu")
		# policy_relu should have shape [batch, 8, 8, 1] so I want [batch, 64]
		value_relu = tf.reshape(value_relu, [-1, 64])
		value_hidden = tf.layers.dense(inputs=value_relu, units=256, activation=tf.nn.relu)
		value_output_layer = tf.layers.dense(inputs=value_hidden, units=1, activation=tf.nn.tanh)

		predictions = tf.concat([policy_output_layer, value_output_layer], axis=1)
		loss = tf.add(
			tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=policy_output_layer, labels=policy_labels)),
			tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=value_output_layer, labels=value_labels))
			)
		eval_metric_ops = {}
		optimizer = tf.train.GradientDescentOptimizer(
			learning_rate=0.1)
		train_op = optimizer.minimize(
			loss=loss, global_step=tf.train.get_global_step())
		
		return tf.estimator.EstimatorSpec(mode, predictions, loss, train_op, eval_metric_ops)
