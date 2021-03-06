#include <opencv2/core/core.hpp>

#include <stdint.h>

#include <string>
#include <vector>
#include <boost/random.hpp>

#include "caffe/common.hpp"
#include "caffe/data_layers.hpp"
#include "caffe/layer.hpp"
#include "caffe/proto/caffe.pb.h"
#include "caffe/util/benchmark.hpp"
#include "caffe/util/io.hpp"
#include "caffe/util/math_functions.hpp"
#include "caffe/util/rng.hpp"

namespace caffe {

template <typename Dtype>
DocDataLayer<Dtype>::~DocDataLayer<Dtype>() {
  this->JoinPrefetchThread();
  while (!prefetch_labels_.empty()) {
    delete prefetch_labels_.back();
	prefetch_labels_.pop_back();
  }
}

template <typename Dtype>
void DocDataLayer<Dtype>::InitRand(unsigned int seed) {
  const unsigned int rng_seed = (seed) ? seed : caffe_rng_rand();
  rng_.reset(new Caffe::RNG(rng_seed));
}

template <typename Dtype>
int DocDataLayer<Dtype>::RandInt(int n) {
  CHECK(rng_);
  CHECK_GT(n, 0);
  caffe::rng_t* rng =
      static_cast<caffe::rng_t*>(rng_->generator());
  return ((*rng)() % n);
}

template <typename Dtype>
float DocDataLayer<Dtype>::RandFloat(float min, float max) {
  CHECK(rng_);
  CHECK_GE(max, min);
  caffe::rng_t* rng =
      static_cast<caffe::rng_t*>(rng_->generator());
  boost::uniform_real<float> random_distribution(min, caffe_nextafter<float>(max));
  boost::variate_generator<caffe::rng_t*, boost::uniform_real<float> >
      variate_generator(rng, random_distribution);
  return variate_generator();
}

template <typename Dtype>
Dtype DocDataLayer<Dtype>::GetLabelValue(DocumentDatum& doc, const std::string& label_name) {
  if (label_name == "country") {
    return doc.has_country() ? doc.country() : missing_value_;
  } else if (label_name == "language") {
    return doc.has_language() ? doc.language() : missing_value_;
  } else if (label_name == "decade") {
    return doc.has_decade() ? doc.decade() : missing_value_;
  } else if (label_name == "column_count") {
    return doc.has_column_count() ? doc.column_count() : missing_value_;
  } else if (label_name == "possible_records") {
    return doc.has_possible_records() ? doc.possible_records() : missing_value_;
  } else if (label_name == "actual_records") {
    return doc.has_actual_records() ? doc.actual_records() : missing_value_;
  } else if (label_name == "pages_per_image") {
    return doc.has_pages_per_image() ? doc.pages_per_image() : missing_value_;
  } else if (label_name == "docs_per_image") {
    return doc.has_docs_per_image() ? doc.docs_per_image() : missing_value_;
  } else if (label_name == "machine_text") {
    return doc.has_machine_text() ? doc.machine_text() : missing_value_;
  } else if (label_name == "hand_text") {
    return doc.has_hand_text() ? doc.hand_text() : missing_value_;
  } else if (label_name == "layout_category") {
    return doc.has_layout_category() ? doc.layout_category() : missing_value_;
  } else if (label_name == "layout_type") {
    return doc.has_layout_type() ? doc.layout_type() : missing_value_;
  } else if (label_name == "record_type_broad") {
    return doc.has_record_type_broad() ? doc.record_type_broad() : missing_value_;
  } else if (label_name == "record_type_fine") {
    return doc.has_record_type_fine() ? doc.record_type_fine() : missing_value_;
  } else if (label_name == "media_type") {
    return doc.has_media_type() ? doc.media_type() : missing_value_;
  } else if (label_name == "is_document") {
    return doc.has_is_document() ? doc.is_document() : missing_value_;
  } else if (label_name == "is_graphical") {
    return doc.has_is_graphical_document() ? doc.is_graphical_document() : missing_value_;
  } else if (label_name == "is_historical") {
    return doc.has_is_historical_document() ? doc.is_historical_document() : missing_value_;
  } else if (label_name == "is_textual") {
    return doc.has_is_textual_document() ? doc.is_textual_document() : missing_value_;
  } else if (label_name == "dbid") {
    return doc.has_dbid() ? doc.dbid() : missing_value_;
  } else if (label_name == "original_aspect_ratio") {
    return doc.has_original_aspect_ratio() ? doc.original_aspect_ratio() : missing_value_;
  } else if (label_name == "num") {
    return doc.has_num() ? doc.num() : missing_value_;
  } else if (label_name == "height") {
    return (Dtype) doc.image().height();
  } else if (label_name == "width") {
    return (Dtype) doc.image().width();
  } else {
    CHECK(0) << "Unrecognized label_name: " << label_name;
  }
  return 0;
}

template <typename Dtype>
int DocDataLayer<Dtype>::SampleCat(const vector<float>& probs) {
  float rand = this->RandFloat(0, 1.0f);
  float cum_prob = 0;
  int i;
  for (i = 0; i < probs.size(); i++) {
    cum_prob += probs[i];
	if (cum_prob >= rand) {
	  break;
    }
  }
  if (i == probs.size()) {
    i--;
  }
  return i;
}

template <typename Dtype>
void DocDataLayer<Dtype>::NextInOrderIndex() {
  if (dbs_.size() == 1) {
    cur_index_ = 0; 
  } else if (cur_index_ == dbs_.size() - 1) {
    if (db_epochs_[cur_index_] == db_epochs_[cur_index_ - 1]) {
      // wrap around to 0th db
      cur_index_ = 0;
    }
  } else if (db_epochs_[cur_index_] > db_epochs_[ cur_index_ + 1 ]) {
    // The current DB has had one more epoch than the next
    cur_index_++;
  }
}

template <typename Dtype>
void DocDataLayer<Dtype>::NextIndex() {
  if (in_order_) {
    NextInOrderIndex();
  } else if (enforce_epochs_) {
	DLOG(INFO) << "Enforce Epochs:";
    vector<int> eligible_indices;
	vector<float> eligible_probs;
	int min_epochs = 999999999;

	// find the least number of epochs taken by any DB
	for (int i = 0; i < db_epochs_.size(); i++) {
	  if (db_epochs_[i] < min_epochs) {
	    min_epochs = db_epochs_[i];
	  }
	}

	// get the probs and indices of all dbs with this size
	for (int i = 0; i < db_epochs_.size(); i++) {
	  if (db_epochs_[i] == min_epochs) {
	    eligible_indices.push_back(i);
		eligible_probs.push_back(probs_[i]);
	    DLOG(INFO) << "Enforce Epochs pushing db: " << i << " with " << db_epochs_[i] << " epochs";
	  }
	}

	// normalize eligile_probs
	float sum = 0;
	for (int i = 0; i < eligible_probs.size(); i++) {
	  sum += eligible_probs[i];
	}
	for (int i = 0; i < eligible_probs.size(); i++) {
	  eligible_probs[i] /= sum;
	}

    cur_index_ = eligible_indices[SampleCat(eligible_probs)];
  } else {
    cur_index_ = SampleCat(probs_);
  }
}

template <typename Dtype>
void DocDataLayer<Dtype>::DataLayerSetUp(const vector<Blob<Dtype>*>& bottom,
      const vector<Blob<Dtype>*>& top) {
  this->InitRand(this->layer_param_.doc_data_param().seed());
  this->image_transformer_ = CreateImageTransformer<Dtype>(this->layer_param_.image_transform_param());
  DocDataParameter doc_param = this->layer_param_.doc_data_param();
  num_labels_ = doc_param.label_names_size();
  missing_value_ = doc_param.missing_value();
  no_wrap_ = doc_param.no_wrap();
  enforce_epochs_ = doc_param.enforce_epochs();
  in_order_ = doc_param.in_order();
 
  CHECK(doc_param.sources_size()) << "No source DBs specified";
  CHECK_EQ(top.size(), num_labels_ + 1) << "Must have a top blob for each type of label";


  // set up the input dbs
  for (int i = 0; i < doc_param.sources_size(); i++) {
    // Open the ith database
    shared_ptr<db::DB> db;
	shared_ptr<db::Cursor> cursor;
    db.reset(db::GetDB(doc_param.backend()));
    db->Open(doc_param.sources(i), db::READ);
	db_epochs_.push_back(0);

	cursor.reset(db->NewCursor());
    // Check if we should randomly skip a few data points
    if (doc_param.rand_skip()) {
      unsigned int skip = this->RandInt(doc_param.rand_skip());
      LOG(INFO) << "Skipping first " << skip << " data points.";
      while (skip-- > 0) {
        cursor->Next();
        if (!cursor->valid()) {
          DLOG(INFO) << "Restarting data prefetching from start.";
          cursor->SeekToFirst();
		  db_epochs_[i] = db_epochs_[i] + 1;
        }
      }
    }
	// Push the db handle, cursor, and weight of the ith db
	dbs_.push_back(db);
	cursors_.push_back(cursor);

	// WARNING: LEVELD doesn't implement NumEntries() because you have to
	//  iterate over the entire DB and count yourself.
	size_t num_entries = db->NumEntries();
	db_sizes_.push_back(num_entries);

    if (doc_param.weights_by_size() && num_entries) {
	  probs_.push_back((float)num_entries);
	} else if (i < doc_param.weights_size()) {
	  probs_.push_back(doc_param.weights(i));
	} else {
      probs_.push_back(1.0f);
	}
  }
  cur_index_ = 0;

  // normalize probability weights
  float sum = 0;
  for (int i = 0; i < probs_.size(); i++) {
    sum += probs_[i];
  }
  for (int i = 0; i < probs_.size(); i++) {
    probs_[i] /= sum;
  }

  // Read a data point, to initialize the prefetch and top blobs.
  DocumentDatum doc;
  doc.ParseFromString(cursors_[cur_index_]->value());
  if (this->layer_param_.doc_data_param().force_color()) {
    doc.mutable_image()->set_channels(3);
  }

  vector<int> in_shape;
  in_shape.push_back(1);
  in_shape.push_back(doc.image().channels());
  in_shape.push_back(doc.image().height());
  in_shape.push_back(doc.image().width());

  // Use data_transformer to infer the expected blob shape from datum.
  image_transformer_->SampleTransformParams(in_shape);
  vector<int> top_shape = image_transformer_->InferOutputShape(in_shape);
  this->transformed_data_.Reshape(top_shape);
  // Reshape top[0] and prefetch_data according to the batch_size.
  top_shape[0] = doc_param.batch_size();
  this->prefetch_data_.Reshape(top_shape);
  top[0]->ReshapeLike(this->prefetch_data_);

  LOG(INFO) << "output data size: " << top[0]->num() << ","
      << top[0]->channels() << "," << top[0]->height() << ","
      << top[0]->width();

  // labels
  for (int i = 0; i < num_labels_; i++) {
    string label_name = doc_param.label_names(i);
	label_names_.push_back(label_name);

    vector<int> label_shape(1, doc_param.batch_size());
    top[i + 1]->Reshape(label_shape);
	prefetch_labels_.push_back(new Blob<Dtype>(label_shape));
  }
  // unused, but prevents errors due to inheritance
  this->output_labels_ = false;

  LOG(INFO) << "DocDataLayer::DataLayerSetup() Done";
}

// This function is used to create a thread that prefetches the data.
template <typename Dtype>
void DocDataLayer<Dtype>::InternalThreadEntry() {
  CPUTimer batch_timer;
  batch_timer.Start();
  double read_time = 0;
  double decode_time = 0;
  double trans_time = 0;
  double label_time = 0;
  double seek_time = 0;
  CPUTimer timer;
  CHECK(this->prefetch_data_.count());
  CHECK(this->transformed_data_.count());

  // Reshape according to the first datum of each batch
  // on single input batches allows for inputs of varying dimension.
  const int batch_size = this->layer_param_.doc_data_param().batch_size();
  DocumentDatum doc;
  doc.ParseFromString(cursors_[cur_index_]->value());
  if (this->layer_param_.doc_data_param().force_color()) {
    doc.mutable_image()->set_channels(3);
  }
  vector<int> in_shape;
  in_shape.push_back(1);
  in_shape.push_back(doc.image().channels());
  in_shape.push_back(doc.image().height());
  in_shape.push_back(doc.image().width());
  DLOG(INFO) << "height: " << doc.image().height() << "\twidth: " << doc.image().width();
  // Use image_transformer to infer the expected blob shape from doc
  image_transformer_->SampleTransformParams(in_shape);
  vector<int> top_shape = image_transformer_->InferOutputShape(in_shape);
  this->transformed_data_.Reshape(top_shape);
  /*
  DLOG(INFO) << "Prefetch db: " << cur_index_ << " Shape: " << 
  	this->transformed_data_.shape_string() << " Doc id: " << doc.id();
  */
  // Reshape prefetch_data according to the batch_size.
  top_shape[0] = batch_size;
  this->prefetch_data_.Reshape(top_shape);

  // reshape the labels
  vector<int> label_shape(1, batch_size);
  for (int i = 0; i < num_labels_; i++) {
	prefetch_labels_[i]->Reshape(label_shape);
  }

  Dtype* top_data = this->prefetch_data_.mutable_cpu_data();
  Dtype* top_label = NULL;  // suppress warnings about uninitialized variables

  timer.Start();
  for (int item_id = 0; item_id < batch_size; ++item_id) {
    // get a datum
    DocumentDatum doc;
    doc.ParseFromString(cursors_[cur_index_]->value());
	//string key = cursors_[cur_index_]->key();
	//LOG(INFO) << "Item " << item_id << " Key: " << key.c_str();
    if (this->layer_param_.doc_data_param().force_color()) {
      doc.mutable_image()->set_channels(3);
    }
    read_time += timer.MicroSeconds();
    timer.Start();
    // Apply data transformations (mirror, scale, crop...)
	
	bool do_color = (doc.image().channels() == 3);
	cv::Mat pretransform_img = ImageToCVMat(doc.image(), do_color);
	decode_time += timer.MicroSeconds();
    timer.Start();
	cv::Mat posttransform_img;
	image_transformer_->Transform(pretransform_img, posttransform_img);

    int offset = this->prefetch_data_.offset(item_id);
    this->transformed_data_.set_cpu_data(top_data + offset);
    image_transformer_->CVMatToArray(posttransform_img, this->transformed_data_.mutable_cpu_data());
    trans_time += timer.MicroSeconds();
    timer.Start();
    // Copy labels
	for (int i = 0; i < num_labels_; i++) {
      top_label = prefetch_labels_[i]->mutable_cpu_data();
      top_label[item_id] = GetLabelValue(doc, label_names_[i]);
	  /*
	  DLOG(INFO) << "item: " << item_id << " label_idx: " << i << " label_name: " << label_names_[i] << 
	  	" label_val: " << GetLabelValue(doc, label_names_[i]);
	  */
	}
	label_time += timer.MicroSeconds();
	timer.Start();

	int num_to_advance = 1;
	if (this->layer_param_.doc_data_param().rand_advance_skip() > 0) {
	  num_to_advance += this->RandInt(this->layer_param_.doc_data_param().rand_advance_skip() + 1);
	}
	bool do_break = false;
	for (int i = 0; i < num_to_advance; i++) {
      // go to the next item.
      cursors_[cur_index_]->Next();
      if (!cursors_[cur_index_]->valid()) {
		db_epochs_[cur_index_] = db_epochs_[cur_index_] + 1;
		cursors_[cur_index_]->SeekToFirst();
        DLOG(INFO) << "Restarting data prefetching from start on db: " << cur_index_;
	    if (no_wrap_) {
          DLOG(INFO) << "Truncating batch to size: " << item_id;
		  do_break = true;

		  // truncate the batch size
          top_shape[0] = item_id + 1;
          this->prefetch_data_.Reshape(top_shape);

          label_shape[0] = item_id + 1;
	      for (int i = 0; i < num_labels_; i++) {
            prefetch_labels_[i]->Reshape(label_shape);
		  }
		  break;
		}
      }
	}
	if (do_break) {
	  break;
	}
	seek_time += timer.MicroSeconds();
	timer.Start();
  }
  timer.Stop();
  batch_timer.Stop();
  /*
  DLOG(INFO) << "Prefetch batch: " << batch_timer.MilliSeconds() << " ms.";
  DLOG(INFO) << "     Read time: " << read_time / 1000 << " ms.";
  DLOG(INFO) << "   Decode time: " << decode_time / 1000 << " ms.";
  DLOG(INFO) << "Transform time: " << trans_time / 1000 << " ms.";
  DLOG(INFO) << "    Label time: " << label_time / 1000 << " ms.";
  DLOG(INFO) << "     Seek time: " << seek_time / 1000 << " ms.";
  */

  // Choose a db at random to pull from on the next batch
  NextIndex();
}


template <typename Dtype>
void DocDataLayer<Dtype>::Forward_cpu(
    const vector<Blob<Dtype>*>& bottom, const vector<Blob<Dtype>*>& top) {
  // First, join the thread
  this->JoinPrefetchThread();
  DLOG(INFO) << "Thread joined";
  DLOG(INFO) << "Prefetch Shape: " << this->prefetch_data_.shape_string();
  // Reshape to loaded data.
  top[0]->ReshapeLike(this->prefetch_data_);
  // Copy the data
  caffe_copy(this->prefetch_data_.count(), this->prefetch_data_.cpu_data(),
             top[0]->mutable_cpu_data());
  DLOG(INFO) << "Prefetch copied";
  for (int i = 0; i < num_labels_; i++) {
    Blob<Dtype>* prefetch_label = prefetch_labels_[i];
    top[i + 1]->ReshapeLike(*prefetch_label);

    caffe_copy(prefetch_label->count(), prefetch_label->cpu_data(),
               top[i + 1]->mutable_cpu_data());
  }
  // Start a new prefetch thread
  DLOG(INFO) << "CreatePrefetchThread";
  this->CreatePrefetchThread();
}

#ifdef CPU_ONLY
STUB_GPU_FORWARD(DocDataLayer, Forward);
#endif

INSTANTIATE_CLASS(DocDataLayer);
REGISTER_LAYER_CLASS(DocData);

}  // namespace caffe
