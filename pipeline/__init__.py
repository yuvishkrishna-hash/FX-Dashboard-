"""FX research dashboard pipeline.

Thread limits are set before NumPy is imported. The Kalman fit is
process-parallel, and extra BLAS threads oversubscribe a small runner.
"""

import os

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
