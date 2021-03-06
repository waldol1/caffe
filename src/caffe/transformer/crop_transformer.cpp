#include <opencv2/core/core.hpp>
#include <opencv2/imgproc/imgproc.hpp>
#include <boost/random.hpp>

#include <string>
#include <vector>

#include "caffe/image_transformer.hpp"
#include "caffe/util/io.hpp"
#include "caffe/util/math_functions.hpp"
#include "caffe/util/rng.hpp"

namespace caffe {

template <typename Dtype>
vector<int> CropImageTransformer<Dtype>::InferOutputShape(const vector<int>& in_shape) {
  CHECK_GT(cur_height_, 0) << "Unitialized current settings: call SampleTransformParams() first";
  CHECK_GT(cur_width_, 0) << "Unitialized current settings: call SampleTransformParams() first";
  CHECK_GT(in_shape.size(), 2);
  CHECK_LE(in_shape.size(), 4);

  vector<int> shape;
  for (int i = 0; i < in_shape.size() - 2; i++) {
    shape.push_back(in_shape[i]);
  }
  shape.push_back(cur_height_);
  shape.push_back(cur_width_);
  return shape;
}

template <typename Dtype>
void CropImageTransformer<Dtype>::SamplePercIndependent(int in_width, int in_height) {
  if (param_.width_perc_size() == 1) {
    cur_width_ = (int) (param_.width_perc(0) * in_width);
  } else {
    Dtype rand;
    this->RandFloat(1, param_.width_perc(0), param_.width_perc(1), &rand);
    cur_width_ = (int) (rand * in_width);
  }
  if (param_.height_perc_size() == 1) {
    cur_height_ = (int) (param_.height_perc(0) * in_height);
  } else {
    Dtype rand;
    this->RandFloat(1, param_.height_perc(0), param_.height_perc(1), &rand);
    cur_height_ = (int) (rand * in_height);
  }
}

template <typename Dtype>
void CropImageTransformer<Dtype>::SamplePercTied(int in_width, int in_height) {
  if (param_.size_perc_size() == 1) {
    cur_width_ = (int) (param_.size_perc(0) * in_width);
    cur_height_ = (int) (param_.size_perc(0) * in_height);
  } else {
    Dtype rand;
    this->RandFloat(1, param_.size_perc(0), param_.size_perc(1), &rand);
    cur_width_ = (int) (rand *  in_width);
    cur_height_ = (int) (rand * in_height);
  }
}

template <typename Dtype>
void CropImageTransformer<Dtype>::SampleFixedIndependent() {
  if (param_.width_size() == 1) {
    cur_width_ = param_.width(0);
  } else {
    cur_width_ = this->RandInt(param_.width(1) - param_.width(0) + 1) + param_.width(0);
  }
  if (param_.height_size() == 1) {
    cur_height_ = param_.height(0);
  } else {
    cur_height_ = this->RandInt(param_.height(1) - param_.height(0) + 1) + param_.height(0);
  }
}

template <typename Dtype>
void CropImageTransformer<Dtype>::SampleFixedTied() {
  if (param_.size_size() == 1) {
    cur_width_ = cur_height_ = param_.size(0);
  } else {
    cur_width_ = cur_height_ = this->RandInt(param_.size(1) - param_.size(0) + 1) + param_.size(0);
  }
}

template <typename Dtype>
void CropImageTransformer<Dtype>::ValidateParam() {
  int num_groups = 0;
  if (param_.width_size()) {
    CHECK(param_.height_size()) << "If width is specified, height must as well";
	CHECK_GT(param_.width(0), 0) << "width must be positive";
	CHECK_GT(param_.height(0), 0) << "height must be positive";

	if (param_.width_size() > 1) {
	  CHECK_GE(param_.width(1), param_.width(0)) << "width upper bound < lower bound";
	}
	if (param_.height_size() > 1) {
	  CHECK_GE(param_.height(1), param_.height(0)) << "height upper bound < lower bound";
	}
	num_groups++;
  }
  if (param_.size_size()) {
	CHECK_GT(param_.size(0), 0) << "Size must be positive";

	if (param_.size_size() > 1) {
	  CHECK_GE(param_.size(1), param_.size(0)) << "size upper bound < lower bound";
	}
	num_groups++;
  }
  if (param_.width_perc_size()) {
    CHECK(param_.height_perc_size()) << "If width_perc is specified, height_perc must as well";
	CHECK_GT(param_.width_perc(0), 0) << "width_perc must be positive";
	CHECK_GT(param_.height_perc(0), 0) << "height_perc must be positive";

	if (param_.width_perc_size() > 1) {
	  CHECK_GE(param_.width_perc(1), param_.width_perc(0)) << "width_perc upper bound < lower bound";
	}
	if (param_.height_perc_size() > 1) {
	  CHECK_GE(param_.height_perc(1), param_.height_perc(0)) << "height_perc upper bound < lower bound";
	}
	num_groups++;
  }
  if (param_.size_perc_size()) {
	CHECK_GT(param_.size_perc(0), 0) << "Size must be positive";

	if (param_.size_perc_size() > 1) {
	  CHECK_GE(param_.size_perc(1), param_.size_perc(0)) << "size_perc upper bound < lower bound";
	}
	num_groups++;
  }

  if (num_groups == 0) {
    CHECK(0) << "No group of resize parameters were specified";
  }
  if (num_groups > 1) {
    CHECK(0) << "Multiple groups of resize parameters were specified";
  }

}

template <typename Dtype>
void CropImageTransformer<Dtype>::SampleTransformParams(const vector<int>& in_shape) {
  CHECK_GE(in_shape.size(), 2);
  CHECK_LE(in_shape.size(), 4);

  ImageTransformer<Dtype>::SampleTransformParams(in_shape);
  int in_width = in_shape[in_shape.size() - 1];
  int in_height = in_shape[in_shape.size() - 2];
  DLOG(INFO) << "in_width: " << in_width << "\tin_height: " << in_height;

  if (param_.width_size()) {
    SampleFixedIndependent();
  } else if (param_.size_size()) {
    SampleFixedTied();
  } else if (param_.width_perc_size()) {
    SamplePercIndependent(in_width, in_height);
  } else if (param_.size_perc_size()) {
    SamplePercTied(in_width, in_height);
  } else {
    CHECK(0) << "Invalid crop param";
  }
  PrintParams();
}

template <typename Dtype>
void CropImageTransformer<Dtype>::Transform(const cv::Mat& in, cv::Mat& out) {
  int crop_h_pos, crop_w_pos;
  int in_height = in.rows;
  int in_width = in.cols;
  CHECK_GE(in_height, cur_height_) << "Cannot crop to larger height";
  CHECK_GE(in_width, cur_width_) << "Cannot crop to larger width";
  switch(param_.location()) {
    case CropTransformParameter::RANDOM:
	  crop_h_pos = this->RandInt(in_height - cur_height_ + 1);
	  crop_w_pos = this->RandInt(in_width - cur_width_ + 1);
	  break;
	case CropTransformParameter::CENTER:
	  crop_h_pos = (in_height - cur_height_) / 2;
	  crop_w_pos = (in_width - cur_width_) / 2;
	  break;
	case CropTransformParameter::RAND_CORNER:
	  {
	    bool left = (bool) this->RandInt(2);
	    bool up = (bool) this->RandInt(2);
	    if (left) {
	      crop_w_pos = 0;
	    } else {
	      crop_w_pos = in_width - cur_width_;
	    }
	    if (up) {
	      crop_h_pos = 0;
	    } else {
	      crop_h_pos = in_height - cur_height_;
	    }
	  }
	  break;
	case CropTransformParameter::UL_CORNER:
	  crop_h_pos = crop_w_pos = 0;
	  break;
	case CropTransformParameter::UR_CORNER:
	  crop_h_pos = 0;
	  crop_w_pos = in_width - cur_width_;
	  break;
	case CropTransformParameter::BL_CORNER:
	  crop_h_pos = in_height - cur_height_;
	  crop_w_pos = 0;
	  break;
	case CropTransformParameter::BR_CORNER:
	  crop_h_pos = in_height - cur_height_;
	  crop_w_pos = in_width - cur_width_;
	  break;
	default:
	  CHECK(0) << "Invalid CropLocation: " << param_.location();
	  break;
  }
  DLOG(INFO) << "(" << this << ") CropTransformer location: (" << crop_h_pos << ", " << crop_w_pos << ")";
  cv::Rect roi(crop_w_pos, crop_h_pos, cur_width_, cur_height_);
  out = in(roi);
}
template <typename Dtype>
void CropImageTransformer<Dtype>::PrintParams() {
  ImageTransformer<Dtype>::PrintParams();
  DLOG(INFO) << "PrintParams (" << this << ") "  << " cur height/width: " << cur_height_ << ", " << cur_width_;
}

INSTANTIATE_CLASS(CropImageTransformer);

}  // namespace caffe
