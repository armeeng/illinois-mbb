import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, LinearRegression
from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
from sklearn.svm import SVR
from sklearn.metrics import mean_absolute_error, r2_score, accuracy_score

df = pd.read_csv("data/lineup_stats.csv")

X = df.loc[:, "ht_delta":]
X_train, X_test, y_train_reg, y_test_reg = train_test_split(X, df["net_eff"], test_size=0.2, random_state=42)
_, _, y_train_cls, y_test_cls = train_test_split(X, (df["net_eff"] > 0).astype(int), test_size=0.2, random_state=42)

rf = SVR()
rf.fit(X_train, y_train_reg)
rf_preds = rf.predict(X_test)
print(f"MAE:       {mean_absolute_error(y_test_reg, rf_preds):.2f}")
print(f"R^2:       {r2_score(y_test_reg, rf_preds):.2f}")
print(f"Train R^2: {r2_score(y_train_reg, rf.predict(X_train)):.2f}")

print()

lr = LogisticRegression(max_iter=5000)
lr.fit(X_train, y_train_cls)
lr_preds = lr.predict(X_test)
majority_baseline = max(y_test_cls.mean(), 1 - y_test_cls.mean())
print(f"Accuracy:  {accuracy_score(y_test_cls, lr_preds):.8f}")
print(f"Baseline:  {majority_baseline:.8f}")
