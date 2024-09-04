import requests, json
import pandas as pd
from pprint import pprint
from IPython.display import display

# base of the url for all endpoints
base_url = 'https://fantasy.premierleague.com/api/'
bootstrap = 'bootstrap-static/'
player_summary = 'element-summary/'


def get_fixture_info(player_id, gw):
    """" Given a player's ID and a gameweek number, returns information about that player's fixture
    on that gameweek (team id, opponent id, home or away) """
    r = requests.get(base_url + player_summary + player_id + '/').json()
    fixtures = r.get('fixtures', [])
    for fixture in fixtures:
        if fixture['event'] == gw:
            is_home = fixture['is_home']
            team_id = fixture['team_h'] if is_home else fixture['team_a']
            opponent_id = fixture['team_a'] if is_home else fixture['team_h']
            return team_id, opponent_id, is_home
    print("Gameweek has already passed")
    return ()


def get_team_difficulty(team_id):
    """" Given a team ID, returns a tuple containing that team's home/away attack and defence ratings
    from FPL API """
    r = requests.get(base_url + bootstrap).json()
    team = r.get('teams', [])[team_id]
    home_att = team['strength_attack_home']
    home_def = team['strength_defence_home']
    away_att = team['strength_attack_away']
    away_def = team['strength_defence_away']
    # remember that home ratings represent the difficulty for another team to play THIS team at home
    # e.g. If Fulham play Liverpool at Craven Cottage, difficulty for Fulham = Liverpool home rating
    return home_att, home_def, away_att, away_def


def get_player_stats(player_id):
    """ Given a player ID, returns a dictionary containing key stats and info about the player """
    r = requests.get(base_url + bootstrap).json()
    player = r.get('elements', [])[player_id]
    return player

