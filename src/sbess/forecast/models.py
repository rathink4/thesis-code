"""Forecasters. Each one predicts an (n_issue, horizon) array for the given issue times.

    persistence : tomorrow looks like today; y_hat[t+k] = y[t+k-24]. The baseline to beat.
    xgboost     : gradient-boosted trees on tabular features, one model for all leads
                  (lead is a feature).
    lstm        : an LSTM reads the last `history_h` hours of measurements; a small network then
                  combines its summary with each target hour's forecast weather and calendar.
All learned models are fitted on the training issue times and use the validation issue times
only to decide when to stop training (early stopping).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
import xgboost as xgb
from torch import nn

from sbess.forecast.data import sequence_features, tabular_features, target_matrix


class Forecaster:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.horizon = cfg["forecast"]["horizon_h"]
        self.info: dict = {}              # training details worth reporting (e.g. epochs used)

    def fit(self, table: pd.DataFrame, target: str, train_pos: np.ndarray, val_pos: np.ndarray):
        return self

    def predict(self, table: pd.DataFrame, target: str, pos: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class Persistence(Forecaster):
    name = "persistence"

    def predict(self, table, target, pos):
        y = table[target].to_numpy()
        return y[pos[:, None] + np.arange(self.horizon)[None, :] - 24]


class XGBoostForecaster(Forecaster):
    name = "xgboost"

    def fit(self, table, target, train_pos, val_pos):
        p = self.cfg["forecast"]["xgboost"]
        Xtr = tabular_features(table, target, train_pos, self.horizon)
        ytr = target_matrix(table, target, train_pos, self.horizon).T.ravel()   # lead-major, like the rows
        Xva = tabular_features(table, target, val_pos, self.horizon)
        yva = target_matrix(table, target, val_pos, self.horizon).T.ravel()
        self.model = xgb.XGBRegressor(
            n_estimators=p["n_estimators"], max_depth=p["max_depth"], learning_rate=p["learning_rate"],
            subsample=p["subsample"], colsample_bytree=p["colsample_bytree"],
            early_stopping_rounds=p["early_stopping_rounds"], random_state=self.cfg["project"]["seed"],
            tree_method="hist", n_jobs=-1)
        self.model.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
        self.info = {"trees_used": int(self.model.best_iteration) + 1}
        return self

    def predict(self, table, target, pos):
        X = tabular_features(table, target, pos, self.horizon)
        return self.model.predict(X).reshape(self.horizon, len(pos)).T


class _Net(nn.Module):
    def __init__(self, n_past: int, n_future: int, hidden: int):
        super().__init__()
        self.lstm = nn.LSTM(n_past, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden + n_future, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, past, future):
        _, (h, _) = self.lstm(past)                                  # summary of the past window
        h = h[-1].unsqueeze(1).expand(-1, future.shape[1], -1)       # same summary for every lead
        return self.head(torch.cat([h, future], dim=-1)).squeeze(-1)


class LSTMForecaster(Forecaster):
    name = "lstm"

    def _arrays(self, table, target, pos):
        past, future = sequence_features(table, target, pos, self.horizon, self.cfg["forecast"]["lstm"]["history_h"])
        past = (past - self.past_mu) / self.past_sd
        future = (future - self.fut_mu) / self.fut_sd
        return np.nan_to_num(past).astype(np.float32), np.nan_to_num(future).astype(np.float32)

    def _tensors(self, table, target, pos):
        pa, fu = self._arrays(table, target, pos)
        y = target_matrix(table, target, pos, self.horizon) / self.y_scale
        return torch.from_numpy(pa), torch.from_numpy(fu), torch.from_numpy(y.astype(np.float32))

    def fit(self, table, target, train_pos, val_pos):
        p = self.cfg["forecast"]["lstm"]
        seed = self.cfg["project"]["seed"]
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)

        # scaling fitted on training data only
        past, future = sequence_features(table, target, train_pos, self.horizon, p["history_h"])
        self.past_mu, self.past_sd = np.nanmean(past, axis=(0, 1)), np.nanstd(past, axis=(0, 1)) + 1e-6
        self.fut_mu, self.fut_sd = np.nanmean(future, axis=(0, 1)), np.nanstd(future, axis=(0, 1)) + 1e-6
        self.y_scale = float(np.nanmean(np.abs(target_matrix(table, target, train_pos, self.horizon)))) or 1.0

        tr, va = self._tensors(table, target, train_pos), self._tensors(table, target, val_pos)
        net = _Net(tr[0].shape[2], tr[1].shape[2], p["hidden"])
        opt = torch.optim.Adam(net.parameters(), lr=p["learning_rate"])
        loss_fn = nn.MSELoss()
        best, best_state, waited, epochs = np.inf, None, 0, 0
        for epoch in range(p["epochs"]):
            net.train()
            order = rng.permutation(len(train_pos))
            for b in range(0, len(order), p["batch_size"]):
                i = torch.from_numpy(order[b:b + p["batch_size"]])
                opt.zero_grad()
                loss_fn(net(tr[0][i], tr[1][i]), tr[2][i]).backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                val = float(loss_fn(net(va[0], va[1]), va[2]))
            epochs = epoch + 1
            if val < best - 1e-6:
                best, waited = val, 0
                best_state = {k: v.clone() for k, v in net.state_dict().items()}
            else:
                waited += 1
                if waited >= p["patience"]:
                    break
        net.load_state_dict(best_state)
        self.net = net
        self.info = {"epochs_run": epochs}
        return self

    def predict(self, table, target, pos):
        pa, fu = self._arrays(table, target, pos)
        self.net.eval()
        with torch.no_grad():
            out = self.net(torch.from_numpy(pa), torch.from_numpy(fu)).numpy()
        return out * self.y_scale


REGISTRY = {"persistence": Persistence, "xgboost": XGBoostForecaster, "lstm": LSTMForecaster}


def make_forecaster(name: str, cfg: dict) -> Forecaster:
    if name not in REGISTRY:
        raise ValueError(f"Unknown forecast model '{name}'. Available: {list(REGISTRY)}")
    return REGISTRY[name](cfg)
