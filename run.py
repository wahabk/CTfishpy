import ctfishpy
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import cv2

lump = ctfishpy.Lumpfish()
ctreader = ctfishpy.CTreader()

for i in range(40,64):
	#ct, stack_metadata = lump.read_tiff(i, r = (0,400))
	ct, stack_metadata = ctreader.read(i, r = (0, 10))

	ctreader.view(ct)

