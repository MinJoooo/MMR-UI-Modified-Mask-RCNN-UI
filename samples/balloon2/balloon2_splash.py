import os
import sys
import json
import datetime
import numpy as np
import skimage.draw

# Root directory of the project and import MaskRCNN
ROOT_DIR = os.path.abspath("../../")
sys.path.append(ROOT_DIR)  # To find local version of the library
from mrcnn.config import Config
from mrcnn import model as modellib, utils

# Directory to save logs and model checkpoints
DEFAULT_LOGS_DIR = os.path.join(ROOT_DIR, "logs")


############################################################
#  Configurations
############################################################

class InferenceConfig(Config):
    """Configuration for training on the toy  dataset.
    Derives from the base Config class and overrides some values.
    """
    # Give the configuration a recognizable name
    NAME = "balloon"

    # Set batch size to 1 since we'll be running inference on
    # one image at a time. Batch size = GPU_COUNT * IMAGES_PER_GPU
    GPU_COUNT = 1
    IMAGES_PER_GPU = 1

    # Number of classes (including background)
    NUM_CLASSES = 1 + 2  # Background + objects

    # Skip detections with < 90% confidence
    DETECTION_MIN_CONFIDENCE = 0.9


############################################################
#  Dataset
############################################################

class BalloonDataset(utils.Dataset):

    def load_balloon(self, dataset_dir, subset):
        """Load a subset of the Balloon dataset.
        dataset_dir: Root directory of the dataset.
        subset: Subset to load: train or val
        """

        # Add classes. (Imported from utils.py)
        self.add_class("balloon", 1, "heart")
        self.add_class("balloon", 2, "star")
        print("class_info:", self.class_info)


        # Train or validation dataset?
        assert subset in ["train", "val"] ### If subset is not 'train' or 'val', call AssertionError
        dataset_dir = os.path.join(dataset_dir, subset)

        # Load annotations
        # We mostly care about the x and y coordinates of each region
        # Note: In VIA 2.0, regions was changed from a dict to a list.
        annotations = json.load(open(os.path.join(dataset_dir, "via_region_data.json"))) ### Required "import json"
        annotations = list(annotations.values()) # don't need the dict keys

        # The VIA tool saves images in the JSON even if they don't have any
        # annotations. Skip unannotated images.
        annotations = [a for a in annotations if a['regions']]

        # Add images
        for a in annotations:
            regions = a['regions'].values()

            # load_mask() needs the image size to convert polygons to masks.
            # Unfortunately, VIA doesn't include it in JSON, so we must read
            # the image. This is only managable since the dataset is tiny.
            image_path = os.path.join(dataset_dir, a['filename'])
            image = skimage.io.imread(image_path)
            height, width = image.shape[:2]

            self.add_image(
                "balloon",
                image_id=a['filename'],  # use file name as a unique image id
                path=image_path,
                width=width, height=height,
                regions=regions)


    def load_mask(self, image_id):
        """Generate instance masks for an image.
        Returns:
        masks: A bool array of shape [height, width, instance count]
            with one mask per instance.
        class_ids: a 1D array of class IDs of the instance masks.
        """
        # If not a balloon dataset image, delegate to parent class.
        image_info = self.image_info[image_id] ### 'image_info' is created by method 'utils.add_image'
        if image_info["source"] != "balloon":
            return super(self.__class__, self).load_mask(image_id)


        # Convert polygons to a bitmap mask of shape
        # [height, width, instance_count]
        info = self.image_info[image_id]
        mask = np.zeros([info["height"], info["width"], len(info["regions"])],
                        dtype=np.uint8)
        class_ids = []

        for i, p in enumerate(info["regions"]):
            # Get indexes of pixels inside the polygon and set them to 1
            p_points = p["shape_attributes"]
            rr, cc = skimage.draw.polygon(p_points['all_points_y'], p_points['all_points_x'])
            mask[rr, cc, i] = 1

            p_class = p["region_attributes"]["display_name"]
            for info in self.class_info:
                if info["name"] == p_class:
                    class_ids.append(info["id"])
        class_ids = np.array(class_ids)

        # Return mask, and array of class IDs of each instance.
        return mask.astype(np.bool), class_ids


    def image_reference(self, image_id):
        """Return the path of the image."""
        info = self.image_info[image_id]
        if info["source"] == "balloon":
            return info["path"]
        else:
            super(self.__class__, self).image_reference(image_id)


############################################################
#  Evaluate Method
############################################################

def color_splash(image, mask):
    """Apply color splash effect.
    image: RGB image [height, width, 3]
    mask: instance segmentation mask [height, width, instance count]

    Returns result image.
    """
    # Make a grayscale copy of the image. The grayscale copy still
    # has 3 RGB channels, though.
    gray = skimage.color.gray2rgb(skimage.color.rgb2gray(image)) * 255
    # Copy color pixels from the original color image where mask is set
    if mask.shape[-1] > 0:
        # We're treating all instances as one, so collapse the mask into one layer
        mask = (np.sum(mask, -1, keepdims=True) >= 1)
        splash = np.where(mask, image, gray).astype(np.uint8)
    else:
        splash = gray.astype(np.uint8)
    return splash


############################################################
#  Training
############################################################

def training(image_path, model_path):

    # Configurations and create model
    config = InferenceConfig()
    model = modellib.MaskRCNN(mode="inference", config=config,
                              model_dir=DEFAULT_LOGS_DIR)

    # Load weights
    print("Loading weights ", model_path)
    model.load_weights(model_path, by_name=True)

    # Evaluate
    # Run model detection and generate the color splash effect
    print("Running on {}".format(image_path))

    # Read image
    image = skimage.io.imread(image_path)

    # Detect objects
    results, text_image, text_molded_images, text_image_metas, text_anchors = model.detect([image], verbose=1)
    r = results[0]

    # Color splash
    splash = color_splash(image, r['masks'])

    # Save output
    filename = "Splash_{:%Y%m%dT%H%M%S}.png".format(datetime.datetime.now())
    skimage.io.imsave(filename, splash)
    print("Saved to ", filename)
    path = os.getcwd()
    path = os.path.join(path, filename)

    return path, text_image, text_molded_images, text_image_metas, text_anchors