from keras.preprocessing import image
from keras.applications.vgg19 import preprocess_input
from keras.models import Model
from keras.layers import Dense, GlobalAveragePooling2D, Flatten, core, Reshape, Input, Activation, Conv2D, MaxPooling2D, UpSampling2D, GaussianNoise, MaxPooling1D, Lambda, Concatenate
from keras.layers.normalization import BatchNormalization
from keras import backend as K
from keras import optimizers, regularizers, metrics
from keras.utils.data_utils import get_file
from keras.models import load_model
from keras import losses
from keras.callbacks import ModelCheckpoint, CSVLogger, LearningRateScheduler, ReduceLROnPlateau
from keras.preprocessing.image import ImageDataGenerator
from keras.models import Sequential
import resnet
import matplotlib.pyplot as plt 
import time, os, glob, sys, datetime
import numpy as np
import load_data
import augmentation as ra
import argparse


#PARAMETERS###########################
input_sizes=[(101, 101)] # size of the input images 

default_augmentation_params = {         
    'zoom_range': (1/1.1, 1.),
    'rotation_range': (0, 180),
    'shear_range': (0, 0),
    'translation_range': (-4, 4),
    'do_flip': True,
}

num_chunks=2000 
chunk_size= 1280 
batch_size= 64 
num_batch_augm=20 
nbands=1
normalize=True   # normalize the images to max of 255 (valid for single-band only)
augm_pred=True    
#load_model=
model_name='my_model'
learning_rate= 0.0001 
	
range_min=0.02
range_max=0.30

########################################
buffer_size=1 
avg_img=0
input_shape=(input_sizes[0][0],input_sizes[0][1],3)
test_path=ra.test_path
test_data=ra.test_data

def iterate_minibatches(inputs, targets, batchsize, shuffle=False):
    assert len(inputs) == len(targets)
    if shuffle:
        indices = np.arange(len(inputs))
        np.random.shuffle(indices)
    for start_idx in range(0, len(inputs) - batchsize + 1, batchsize):
        if shuffle:
            excerpt = indices[start_idx:start_idx + batchsize]
        else:
            excerpt = slice(start_idx, start_idx + batchsize)
        yield inputs[excerpt], targets[excerpt]       

	
def build_resnet():

	model=resnet.ResnetBuilder.build_resnet_18(input_shape,1)#18
	
	
	return model

def call_model(model='resnet'):
			
	
	if model == 'resnet':
		multi_model = build_resnet()

	return multi_model

def main(model='resnet', mode='train', num_chunks=num_chunks, chunk_size=chunk_size, input_sizes=input_sizes, batch_size=batch_size, nbands=nbands, model_name=model_name):   

	multi_model=call_model(model=model)

	if mode=='train':
			
		loss=optimizers.Adam(lr=learning_rate)
		
		multi_model.compile(optimizer=loss, loss='binary_crossentropy', metrics=[metrics.binary_accuracy])  
		
		if nbands==3:
			augmented_data_gen_pos = ra.realtime_augmented_data_gen_pos_col(num_chunks=num_chunks, chunk_size=chunk_size, target_sizes=input_sizes, augmentation_params=default_augmentation_params)
			augmented_data_gen_neg = ra.realtime_augmented_data_gen_neg_col(num_chunks=num_chunks, chunk_size=chunk_size, target_sizes=input_sizes, augmentation_params=default_augmentation_params)
			  
		else:
			augmented_data_gen_pos = ra.realtime_augmented_data_gen_pos(range_min=range_min, range_max=range_max, num_chunks=num_chunks, chunk_size=chunk_size, target_sizes=input_sizes, normalize=normalize , resize=resize, augmentation_params=default_augmentation_params)      
			augmented_data_gen_neg = ra.realtime_augmented_data_gen_neg(num_chunks=num_chunks, chunk_size=chunk_size, target_sizes=input_sizes, normalize=normalize, resize=resize,augmentation_params=default_augmentation_params)      
			
		train_gen_neg = load_data.buffered_gen_mp(augmented_data_gen_neg, buffer_size=buffer_size) 
		train_gen_pos = load_data.buffered_gen_mp(augmented_data_gen_pos, buffer_size=buffer_size) 
		
		try:
			for chunk in range(num_chunks):
				start_time = time.time()
				chunk_data_pos, chunk_length = next(train_gen_pos)  
				y_train_pos = chunk_data_pos.pop()                   
				X_train_pos = chunk_data_pos
			
				chunk_data_neg, _ = next(train_gen_neg)  
				y_train_neg = chunk_data_neg.pop()                   
				X_train_neg = chunk_data_neg
			
				X_train = np.concatenate((X_train_pos[0],X_train_neg[0]))
				y_train=np.concatenate((y_train_pos,y_train_neg))
				y_train=y_train.astype(np.int32)
				y_train = np.expand_dims(y_train, axis=1)
				train_batches = 0
				batches = 0
				for batch in iterate_minibatches(X_train, y_train, batch_size, shuffle=True):
					X_batch, y_batch = batch
					train = multi_model.fit(X_batch/255.-avg_img, y_batch)
					batches += 1
				X_train=None
				y_train=None
				print(chunk)
				print(time.time()- start_time)
			
		except KeyboardInterrupt:
			#multi_model.save(model_name+'_last.h5')
			multi_model.save_weights(model_name+'_weights_only.h5')
			print('interrupted!')
			print('saved weights')
		
		#multi_model.save(model_name+'_last.h5')
		multi_model.save_weights(model_name+'_weights_only.h5')
		end_time = time.time()
		print('time employed ', end_time-start_time)

	if mode=='predict':
		if nbands==3:
			augmented_data_gen_test_fixed = ra.realtime_fixed_augmented_data_test_col(target_sizes=input_sizes)#,normalize=normalize)
		else:
			augmented_data_gen_test_fixed = ra.realtime_fixed_augmented_data_test(target_sizes=input_sizes)
			
		test_gen_fixed = load_data.buffered_gen_mp(augmented_data_gen_test_fixed, buffer_size=2)
		
		multi_model.load_weights(model_name+'_weights_only.h5')

		predictions=[]
		test_batches = 0
		if augm_pred==True:
			start_time=time.time()
			for e, (chunk_data_test, chunk_length_test) in enumerate(test_gen_fixed):
				X_test = chunk_data_test
				X_test = X_test[0]
				X_test=X_test/255.-avg_img
				pred1=multi_model.predict(X_test) 
				pred2=multi_model.predict(np.array([np.flipud(image) for image in X_test]))
				pred3=multi_model.predict(np.array([np.fliplr(np.flipud(image)) for image in X_test]))
				pred4=multi_model.predict(np.array([np.fliplr(image) for image in X_test]))
				preds=np.mean([pred1, pred2, pred3, pred4], axis=0)
				preds=preds.tolist()
				predictions = predictions + preds
	
		else:
			for e, (chunk_data_test, chunk_length_test) in enumerate(test_gen_fixed):
				X_test = chunk_data_test
				X_test = X_test[0]
				X_test=X_test/255.-avg_img
				pred1=multi_model.predict(X_test) 
				preds=pred1.tolist()
				predictions = predictions + preds		

		with open('pred_'+model_name+'.pkl', 'wb') as f:
			pickle.dump([[ra.test_data],[predictions]], f, pickle.HIGHEST_PROTOCOL)
		
if __name__ == "__main__":
    kwargs = {}
    if len(sys.argv) > 1:
        kwargs['model'] = sys.argv[1]
    if len(sys.argv) > 2:
        kwargs['mode'] = sys.argv[2]
    if len(sys.argv) > 3:
        kwargs['model_name'] = sys.argv[3]
    main(**kwargs)
        
        
    
    
    
