"""Day-ahead forecasting of community load and PV (Weeks 4-5).

data.py      one continuous hourly table (actuals + weather forecast + calendar) and the
             leak-free samples built from it
models.py    persistence, XGBoost and LSTM forecasters with one common interface
pipeline.py  split by date, train, evaluate on the test year, save forecasts for the brains
"""
