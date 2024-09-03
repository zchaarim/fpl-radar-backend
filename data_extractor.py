import requests, json
import pandas as pd
from pprint import pprint
from IPython.display import display

# base of the url for all endpoints
base_url = 'https://fantasy.premierleague.com/api/'

# use bootstrap-static/ endpoint
r = requests.get(base_url + 'bootstrap-static/').json()

# show top-level fields
pprint(r, indent=2, depth=1, compact=True)

# get player data
players = r['elements']

# show data for first player
pprint(players)

pd.set_option('display.max_columns', None)

# create players dataframe
players = pd.json_normalize(players)

# display(players[['id', 'web_name', 'team', 'element_type']].head())

# extract other information
teams = pd.json_normalize(r['teams'])

positions = pd.json_normalize(r['element_types'])

# merge to get data on every player
df = pd.merge(left=players, right=teams, left_on='team', right_on='id')

display(df[['first_name', 'second_name', 'name']].head())

df = df.merge(positions, left_on='element_type', right_on='id')

df= df.rename(columns={'name':'team_name', 'singular_name':'position_name'})

display(df[['first_name', 'second_name', 'team_name', 'position_name']])




