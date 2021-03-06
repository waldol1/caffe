
import cv2
import numpy as np
import sys

im1 = cv2.imread(sys.argv[1], -1)
im2 = cv2.imread(sys.argv[2], -1)
assert im1.shape == im2.shape

im3 = np.zeros(shape=im1.shape + (3,), dtype=np.uint8)

im1_bool = im1 < 128
im2_bool = im2 < 128

im_combined = 2 * im1_bool + im2_bool

im3[im_combined == 0] = [255, 255, 255]
im3[im_combined == 1] = [0, 0, 255]
im3[im_combined == 2] = [0, 255, 0]
im3[im_combined == 3] = [0, 0, 0]

cv2.imwrite(sys.argv[3], im3)


