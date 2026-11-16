from finlab import data

close = data.get("price:收盤價")
print(close.index.min(), close.index.max())
print(close["2330"].tail())

