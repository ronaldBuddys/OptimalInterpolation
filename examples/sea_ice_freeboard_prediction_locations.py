# ------------------------------------------------------------
# ------------------------------------------------------------
#
#                   SCRIPT STARTS HERE
#
# ------------------------------------------------------------
# ------------------------------------------------------------


# calculate the hyper-parameters for GP on freeboard cover using a config
# - date(s)
# - window size
# - radius of inclusion
# - freeboard season

import json
import os

import pandas as pd

from OptimalInterpolation import get_data_path, get_path
from OptimalInterpolation.sea_ice_freeboard import SeaIceFreeboard


pd.set_option("display.max_columns", 200)

# #  change output_base_dir as needed
# output_base_dir = get_path("results")
# output_base_dir = os.path.join(gdrive_mount, "MyDrive", "Dissertation")
from OptimalInterpolation import read_key_from_config

# gdrive = read_key_from_config("directory_locations",
#                               "gdrive",
#                               example="gdrive")
# output_base_dir = os.path.join(gdrive, "Dissertation")

output_base_dir = get_path("results")

# ---
# input config
# ---

config = {
    "dates": ["20181201"],
    # "use_raw_data": True,
    # "dates": ["20190201"],
    "optimise": True,
    "file_suffix": "",
    "output_dir": os.path.join(output_base_dir, "pred_loc"),
    # "inclusion_radius": 300,
    "inclusion_radius": 300,
    "days_ahead": 4,
    "days_behind": 4,
    "data_dir": "package",
    "season": "2018-2019",
    "grid_res": 50,
    "coarse_grid_spacing": 15,
    "min_inputs": 500,
    "verbose": 1,
    # "engine": "GPflow_svgp",
    "kernel": "Matern32",
    # "prior_mean_method": "demean_outputs",
    "prior_mean_method": "fyi_average",
    "hold_out": None,
    "load_params": True,
    "predict_on_hold": True,
    "scale_inputs": True,
    "scale_outputs": False,
    "bound_length_scales": True,
    "append_to_file": True,
    "overwrite": False,
    "post_process": {
        "prev_results_dir": None,
        "prev_results_file": None,
        "clip_and_smooth": False,
        "vmax_map": {
            "ls_x": 2 * 300 * 1000,
            "ls_y": 2 * 300 * 1000,
            "ls_t": 9,
            "kernel_variance": 0.1,
            "likelihood_variance": 0.05
        },
        "vmin_map": {
            "ls_x": 1,
            "ls_y": 1,
            "ls_t": 1e-6,
            "kernel_variance": 2e-6,
            "likelihood_variance": 2e-6
        }
    },
    "inducing_point_params": {
        "num_inducing_points": 500,
        "min_obs_for_svgp": 500
    },
    # when not using minbatch can use a low (150?) number for maxiter
    "optimise_params": {
        "use_minibatch": False,
        "gamma": 1.0,
        "learning_rate": 0.07,
        "trainable_inducing_variable": False,
        "minibatch_size": 2000,
        "maxiter": 150,
        "log_freq": 10,
        "persistence": 10,
        "early_stop": True,
        "save_best": True
    }
}

# ---
# parameters
# ---

print("using config:")
print(json.dumps(config, indent=4))

# extract parameters from config

season = config.get("season", "2018-2019")
assert season == "2018-2019", "only can handle data inputs from '2018-2019' season at the moment"

dates = config['dates']
output_dir = config['output_dir']
optimise = config.get('optimise', False)
days_ahead = config.get("days_ahead", 4)
days_behind = config.get("days_behind", 4)
season = config.get("season", "2018-2019")
data_dir = config.get("data_dir", "package")

incl_rad = config.get("inclusion_radius", 300)
grid_res = config.get("grid_res", 25)
coarse_grid_spacing = config.get("coarse_grid_spacing", 1)
min_inputs = config.get("min_inputs", 10)
# min sea ice cover - when loading data set sie to nan if < min_sie
min_sie = config.get("min_sie", 0.15)

engine = config.get("engine", "GPflow")
kernel = config.get("kernel", "Matern32")
prior_mean_method = config.get("prior_mean_method", "fyi_average")
hold_out = config.get("hold_out", None)

scale_inputs = config.get("scale_inputs", False)
scale_inputs = [1 / (grid_res * 1000), 1 / (grid_res * 1000), 1.0] if scale_inputs else [1.0, 1.0, 1.0]

scale_outputs = config.get("scale_outputs", False)
scale_outputs = 100. if scale_outputs else 1.

append_to_file = config.get("append_to_file", True)
overwrite = config.get("overwrite", True)

# use holdout location as GP location selection criteria (in addition to coarse_grid_spacing, etc)
pred_on_hold_out = config.get("predict_on_hold", True)

bound_length_scales = config.get("bound_length_scales", True)

mean_function = config.get("mean_function", None)
file_suffix = config.get("file_suffix", "")
post_process_config = config.get("post_process", {})

load_params = config.get("load_params", False)

inducing_point_params = config.get("inducing_point_params", {})

optimise_params = config.get("optimise_params", {})

use_raw_data = config.get("use_raw_data", False)

# -----
# initialise SeaIceFreeboard object
# -----

sifb = SeaIceFreeboard(grid_res=f"{grid_res}km",
                       length_scale_name=["x", "y", "t"],
                       verbose=3,
                       rng_seed=1234)

# ---
# read / load data
# ---

if data_dir == "package":
    data_dir = get_data_path()

assert os.path.exists(data_dir)

sifb.load_data(aux_data_dir=os.path.join(data_dir, "aux"),
               sat_data_dir=os.path.join(data_dir, "CS2S3_CPOM"),
               raw_data_dir=os.path.join(data_dir, "RAW"),
               season=season)


# ---
# initial run - calculate hyper parameter smoothing
# ---

date = dates[0]
hold_out = None
engine = "GPflow_svgp"
use_raw_data = False

# store prediction results in dict
p = {}

for pred_locs in ["center_only",
                  "neighbour_cell_centers",
                  {"name": "evenly_spaced_in_cell", "n": 100},
                  # "obs_in_cell",
                  ["center_only", {"name": "evenly_spaced_in_cell", "n": 100}]
]:

    if isinstance(pred_locs, str):
        file_suffix = pred_locs
    elif isinstance(pred_locs, dict):
        file_suffix = pred_locs['name']
    elif isinstance(pred_locs, list):
        file_suffix = "".join([_ if isinstance(_, str) else _['name'] for _ in pred_locs])

    file_suffix = engine + "_" + file_suffix
    print("-"*100)
    print("-" * 100)
    print(f"file_suffix: {file_suffix}")

    res, preds, files = sifb.run(date=date,
                                 output_dir=output_dir,
                                 days_ahead=days_ahead,
                                 days_behind=days_behind,
                                 incl_rad=incl_rad,
                                 grid_res=grid_res,
                                 coarse_grid_spacing=coarse_grid_spacing,
                                 min_inputs=min_inputs,
                                 min_sie=min_sie,
                                 engine=engine,
                                 kernel=kernel,
                                 overwrite=False,
                                 load_params=load_params,
                                 prior_mean_method=prior_mean_method,
                                 optimise=True,
                                 season=season,
                                 hold_out=hold_out,
                                 scale_inputs=scale_inputs,
                                 scale_outputs=scale_outputs,
                                 append_to_file=append_to_file,
                                 pred_on_hold_out=pred_on_hold_out,
                                 bound_length_scales=bound_length_scales,
                                 mean_function=mean_function,
                                 file_suffix=file_suffix,
                                 post_process=post_process_config,
                                 print_every=50,
                                 inducing_point_params=inducing_point_params,
                                 optimise_params=optimise_params,
                                 skip_if_pred_exists=False,
                                 use_raw_data=use_raw_data,
                                 predict_locations=pred_locs)

    p[file_suffix] = preds