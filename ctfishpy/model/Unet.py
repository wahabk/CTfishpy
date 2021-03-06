from ..controller import CTreader
import matplotlib.pyplot as plt
import numpy as np
import time
import json
import segmentation_models as sm
import tensorflow.keras as keras
from tensorflow.keras.callbacks import ModelCheckpoint, LearningRateScheduler
from tensorflow.keras.layers import Input, Conv2D
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.preprocessing.image import ImageDataGenerator


class Unet():
	def __init__(self):
		self.shape = (224,224)
		self.roiZ = 125
		self.organ = 'Otoliths'
		self.sample = [200,218,240,277,330,337,341,462,464,40]
		self.val_sample = [78, 364]
		self.val_steps = 8
		self.batch_size = 64
		self.steps_per_epoch = 34
		self.epochs = 100
		self.lr = 1e-5
		self.BACKBONE = 'resnet34'
		self.weights = 'imagenet'
		self.weightspath = 'output/Model/unet_checkpoints.hdf5'
		# 'output/Model/unet_checkpoints.hdf5'
		self.encoder_freeze=True
		self.nclasses = 3
		self.activation = 'softmax'

	def getModel(self):

		dice_loss = sm.losses.DiceLoss(class_weights=np.array([1,5,5])) 
		focal_loss = sm.losses.CategoricalFocalLoss()
		total_loss = dice_loss + (1 * focal_loss)

		optimizer = Adam(learning_rate=self.lr)

		base_model = sm.Unet(self.BACKBONE, encoder_weights=self.weights, classes=self.nclasses, activation=self.activation, encoder_freeze=self.encoder_freeze)
		inp = Input(shape=(self.shape[0], self.shape[1], 1))
		l1 = Conv2D(3, (1, 1))(inp) # map N channels data to 3 channels
		out = base_model(l1)
		model = Model(inp, out, name=base_model.name)

		model.compile(optimizer=optimizer, loss=total_loss, metrics=[])
		return model

	def train(self):
		self.trainstarttime = time.strftime("%Y-%m-%d-%H-%M")
		data_gen_args = dict(rotation_range=10, # degrees
                    width_shift_range=10, #pixels
                    height_shift_range=10,
                    shear_range=5, #degrees
                    zoom_range=0.1, # up to 1
                    horizontal_flip=True,
                    vertical_flip = True,
                    fill_mode='constant',
                    cval = 0)

		xtrain, ytrain, sample_weights = self.dataGenie(batch_size=self.batch_size,
                        data_gen_args = data_gen_args,
                        fish_nums = self.sample)

		xval, yval, sample_weights = self.dataGenie(batch_size = self.batch_size,
				data_gen_args = dict(),
				fish_nums = self.val_sample)
		model = self.getModel()

		model_checkpoint = ModelCheckpoint(self.weightspath, monitor = 'loss', verbose = 1, save_best_only = True)


		callbacks = [
			keras.callbacks.LearningRateScheduler(lr_scheduler, verbose=1),
			model_checkpoint
		]
		
		history = model.fit(xtrain, y=ytrain, validation_data=(xval, yval), steps_per_epoch = self.steps_per_epoch, 
                    	epochs = self.epochs, callbacks=callbacks, validation_steps=self.val_steps)
		self.history = history

	def makeLossCurve(self):
		history = self.history
		plt.plot(history.history['loss'])
		plt.plot(history.history['val_loss'])
		plt.title(f'Unet-otolith loss (lr={self.lr})')
		plt.ylabel('loss')
		plt.xlabel('epoch')
		plt.ylim(0,1)
		plt.legend(['train', 'val'], loc='upper left')
		plt.savefig(f'output/Model/loss_curves/{self.trainstarttime}_loss.png')

	def test(self):
		# TODO setup proper end test
		pass

	def predict(self, n):
		base_model = sm.Unet(self.BACKBONE, classes=self.nclasses, activation=self.activation, encoder_freeze=self.encoder_freeze)
		inp = Input(shape=(self.shape[0], self.shape[1], 1))
		l1 = Conv2D(3, (1, 1))(inp) # map N channels data to 3 channels
		out = base_model(l1)
		model = Model(inp, out, name=base_model.name)
		model.load_weights(self.weightspath)

		test = self.testGenie(n)
		results = model.predict(test, self.batch_size) # read about this one

		label = np.zeros(results.shape[:-1], dtype = 'uint8')
		for i in range(self.nclasses):
			result = results[:, :, :, i]
			label[result>0.5] = i
			
		return label
	
	def dataGenie(self, batch_size, data_gen_args, fish_nums):
		imagegen = ImageDataGenerator(**data_gen_args, rescale = 1./65535)
		maskgen = ImageDataGenerator(**data_gen_args)
		ctreader = CTreader()

		centres_path = ctreader.dataset_path / 'Metadata/cc_centres_Otoliths.json'
		with open(centres_path, 'r') as fp:
			centres = json.load(fp)

		roiZ=self.roiZ
		roiSize=self.shape[0]
		seed = 2
		num_classes = self.nclasses

		ct_list, label_list = [], []
		for num in fish_nums:
			# take out cc for now
			# center, error = cc(num, template, thresh=200, roiSize=50)
			center = centres[str(num)]
			z_center = center[0] # Find center of cc result and only read roi from slices

			ct, stack_metadata = ctreader.read(num, r = (z_center - int(roiZ/2), z_center + int(roiZ/2)), align=True)
			label = ctreader.read_label('Otoliths', n=num,  align=True)
			
			label = ctreader.crop_around_center3d(label, center = center, roiSize=roiSize, roiZ=roiZ)
			center[0] = int(roiZ/2) # Change center to 0 because only read necessary slices but cant do that with labels since hdf5
			ct = ctreader.crop_around_center3d(ct, center = center, roiSize=roiSize, roiZ=roiZ)

			new_mask = np.zeros(label.shape + (num_classes,))
			for i in range(num_classes):
				if i == 2 and self.organ == 'Otoliths': continue # skip utricular otoliths
				#for one pixel in the image, find the class in mask and convert it into one-hot vector
				new_mask[label == i,i] = 1
			
			mask = np.reshape(new_mask,(new_mask.shape[0],new_mask.shape[1],new_mask.shape[2],new_mask.shape[3]))
			label = mask
			ct_list.append(ct)
			label_list.append(label)
			ct, label = None, None
		
		ct_list = np.vstack(ct_list)
		label_list = np.vstack(label_list)
		ct_list = np.array(ct_list, dtype='float32')
		label_list = np.array(label_list, dtype='float32')
		ct_list      = ct_list[:,:,:,np.newaxis] # add final axis to show datagens its grayscale

		print('[dataGenie] Initialising image and mask generators')

		image_generator = imagegen.flow(ct_list,
			batch_size = batch_size,
			#save_to_dir = 'output/Keras/',
			save_prefix = 'dataGenie',
			seed = seed,
			shuffle=True,
			)
		mask_generator = maskgen.flow(label_list, 
			batch_size = batch_size,
			#save_to_dir = 'output/Keras/',
			save_prefix = 'dataGenie',
			seed = seed,
			shuffle=True
			)
		
		print('Ready.')

		#extract data frin generatirs
		test_batches = [image_generator, mask_generator]
		xdata, ydata = [], []
		for i in range(0,int(len(ct_list)/batch_size)):
			xdata.extend(np.array(test_batches[0][i]))
			ydata.extend(np.array(test_batches[1][i]))

		# sample_weights and data extracted in case i need to focus 
		# on slices that arent empty
		sample_weights = []

		return np.array(xdata), np.array(ydata), sample_weights

	def testGenie(self, n):
		ctreader = CTreader()
		# center, error = cc(num, template, thresh=200, roiSize=50)
		centres_path = ctreader.dataset_path / f'Metadata/cc_centres_{self.organ}.json'
		with open(centres_path, 'r') as fp:
			centres = json.load(fp)
		
		center = centres[str(n)]
		z_center = center[0] # Find center of cc result and only read roi from slices
		roiZ=self.roiZ
		roiSize=self.shape[0]
		ct, stack_metadata = ctreader.read(n, r = (z_center - int(roiZ/2), z_center + int(roiZ/2)), align=True)#(1400,1600))
		center[0] = int(roiZ/2)
		ct = ctreader.crop_around_center3d(ct, center = center, roiSize=roiSize, roiZ=roiZ)
		ct = np.array([_slice / 65535 for _slice in ct], dtype='float32') # Normalise 16 bit slices
		ct = ct[:,:,:,np.newaxis] # add final axis to show datagens its grayscale
		return ct



def lr_scheduler(epoch, learning_rate):
	decay_rate = 1
	decay_step = 13
	if epoch % decay_step == 0 and epoch != 0 and epoch != 1:
		return learning_rate * decay_rate
	return learning_rate

def fixFormat(batch, label = False):
    # change format of image batches to make viewable with ctreader
    if not label: return np.squeeze(batch.astype('uint16'), axis = 3)
    if label: return np.squeeze(batch.astype('uint8'), axis = 3)
