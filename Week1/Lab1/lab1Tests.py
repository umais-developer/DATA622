import pandas as pd

auto=pd.read_csv('DataSets/Auto.csv', na_values='?')

auto = auto.dropna()
print(auto.dtypes)
quant_cols = ['mpg', 'cylinders', 'displacement', 'horsepower', 'weight', 'acceleration', 'year','origin']
min_max=auto[quant_cols].agg(['min', 'max'])
print(min_max)


