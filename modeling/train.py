import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, LinearRegression
from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error, r2_score, accuracy_score
import joblib

df = pd.read_csv("data/lineup_stats.csv")

X = df.loc[:, "ht_delta":]
y = df["net_eff"]

model = LGBMRegressor(max_depth=5, n_estimators=10)
model.fit(X, y)
joblib.dump(model, "modeling/models/lineup_model.joblib")
