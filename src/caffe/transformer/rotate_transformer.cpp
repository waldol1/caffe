
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
void RotateImageTransformer<Dtype>::Transform(const cv::Mat& in, cv::Mat& out) {
  Dtype angle = 0.;
  Dtype negative = 0.;
  if (param_.max_angle() > 0 && param_.max_angle() > param_.min_angle()) {
    this->RandFloat(1, param_.min_angle(), param_.max_angle(), &angle); 
    this->RandFloat(1, 0., 1., &negative);
    if (negative <= param_.prob_negative()) {
    	angle = -1 * angle;
    }
  }
  // out uses the same number of channels as in, but uses floats
  out.create(in.size(), CV_32F | (0x18 & in.type()));

  const int in_height = in.rows;
  const int in_width = in.cols;
  cv::Point2f pt(in_height / 2., in_width / 2.);
  int interpolation = this->GetInterpolation(param_.interpolation());
  int border_mode = this->GetBorderMode(param_.border_mode());
  cv::Scalar border_val(param_.border_val());

  cv::Mat rotate = cv::getRotationMatrix2D(pt, (float)angle, 1.0);
  cv::warpAffine(in, out, rotate, in.size(), interpolation, border_mode, border_val);
}

INSTANTIATE_CLASS(RotateImageTransformer);

}  // namespace caffe
