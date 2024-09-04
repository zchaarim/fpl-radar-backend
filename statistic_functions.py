import extractor_functions


# use fantasy.premierleague.com/api/element-summary/{player_id}/ for player fixtures
# use fantasy.premierleague.com/ap/bootstrap-static/ and tag "teams" for in-depth difficulty
def calculate_fdr_multiple_gw(player_id, start_gw, end_gw):
    """ Given a specific player ID and a range of gameweeks to look over, calculates the
    average attacking and defending FDR over those gameweeks """
    total_fdr = [0, 0]
    total_att_fdr = 0
    total_def_fdr = 0
    num_gw = end_gw - start_gw + 1
    for k in range(start_gw, end_gw + 1):
        fdr = calculate_fdr_single_gw(k, player_id)
        total_att_fdr += fdr[0]
        total_def_fdr += fdr[1]

    avg_att_fdr = (total_att_fdr / num_gw)
    avg_def_fdr = (total_def_fdr / num_gw)
    return [avg_att_fdr, avg_def_fdr]


def calculate_fdr_single_gw(player_id, gw):
    """ Given a gameweek number and player ID, returns a tuple of the form (att_fdr, def_fdr) containing
    the attacking and defending difficulty rating for that gameweek """
    fixture_info = extractor_functions.get_fixture_info(player_id, gw)
    # fixture_info is a tuple of form (team_id, opponent_id, is_home)
    team_ratings = extractor_functions.get_team_difficulty(fixture_info[0])
    opp_ratings = extractor_functions.get_team_difficulty(fixture_info[1])
    # team ratings are tuples of form (home_att, home_def, away_att, away_def)
    if fixture_info[2]:
        opp_att = opp_ratings[0]
        opp_def = opp_ratings[1]
        team_att = team_ratings[2]
        team_def = team_ratings[3]
    else:
        opp_att = opp_ratings[2]
        opp_def = opp_ratings[3]
        team_att = team_ratings[0]
        team_def = team_ratings[1]

    return ratings_to_fdr((team_att, team_def, opp_att, opp_def))


def ratings_to_fdr(ratings):
    """ Given player team and opposition attack and defence ratings for a fixture in a list, converts this into
     an attacking and defending fixture difficulty rating for the player team """
    normalised_ratings = []
    # ratings list in form [team_att, team_def, opp_att, opp_def]
    for rating in ratings:
        # convert to a normalised rating between 0 and 1
        normalised_rating = (rating - 1050)/(1400 - 1050)
        normalised_ratings.append(normalised_rating)
    # attacking fdr = team attack - opp defence, defending fdr = team defence - opp attack
    # the higher the fdr score, the better - negative scores indicate bad fixture
    # fdr ranges from -1 to 1
    att_fdr = normalised_ratings[0] - normalised_ratings[3]
    def_fdr = normalised_ratings[1] - normalised_ratings[2]
    return [att_fdr, def_fdr]


def player_rating_single_gw(player_id, gw):
    """ Calculate a rating score for a player's predicted points in a particular gameweek """
    stats = extractor_functions.get_player_stats(player_id)
    fdr = calculate_fdr_single_gw(player_id, gw)
    return rate_player(stats, fdr)


def player_rating_multiple_gw(player_id, start_gw, end_gw):
    """ Calculate a rating score for a player's predicted points over multiple gameweeks """
    stats = extractor_functions.get_player_stats(player_id)
    avg_fdr = calculate_fdr_multiple_gw(player_id, start_gw, end_gw)
    return rate_player(stats, avg_fdr)


def rate_player(stats, fdr):
    """ Given a players stats and an FDR, returns a rating for predicted points """
    # if player is a goalkeeper
    if stats['element_type'] == 1:
        return goalkeeper_rating(stats, fdr)
    # if player is a defender
    elif stats['element_type'] == 2:
        return defender_rating(stats, fdr)
    # if player is a midfielder
    elif stats['element_type'] == 3:
        return midfielder_rating(stats, fdr)
    # if player is a forward
    elif stats['element_type'] == 4:  # player is a forward
        return forward_rating(stats, fdr)
    return 0


def goalkeeper_rating(stats, fdr):
    defensive_score = (
        4 * stats['clean_sheets_per_90'] +
        1 * (stats['saves_per_90'] / 3) +
        (-1) * (stats['goals_conceded_per_90'] / 2)
    )
    score = (
        defensive_score * (0.5 * fdr[1] + 1) +  # Apply defensive FDR
        stats['bonus'] +
        (-0.5) * stats['expected_goals_conceded_per_90']
    )
    return score


def defender_rating(stats, fdr):
    defensive_score = (
            4 * stats['clean_sheets_per_90'] +
            (-1) * (stats['goals_conceded_per_90'] / 2)
    )
    attacking_score = (
            6 * stats['goals_scored'] +
            3 * stats['assists'] +
            3 * stats['expected_goals_per_90'] +
            2 * stats['expected_assists_per_90']
    )
    score = (
        defensive_score * (0.5 * fdr[1] + 1) +  # Apply defensive FDR
        attacking_score * (0.5 * fdr[0] + 1) +  # Apply attacking FDR
        stats['bonus'] +
        0.5 * float(stats['ict_index'])
    )
    return score


def midfielder_rating(stats, fdr):
    print(stats['web_name'])
    defensive_score = 1 * stats['clean_sheets_per_90']
    print("Defensive score = " + str(defensive_score))
    print("Defensive FDR = " + str(fdr[1]))
    attacking_score = (
            5 * stats['goals_scored'] +
            3 * stats['assists'] +
            3 * stats['expected_goals_per_90'] +
            2 * stats['expected_assists_per_90']
    )
    print("Attacking score = " + str(attacking_score))
    print("Attacking FDR = " + str(fdr[0]))
    score = (
            defensive_score * (0.25 * fdr[1] + 1) +  # Apply defensive FDR with reduced weight
            attacking_score * (0.5 * fdr[0] + 1) +  # Apply attacking FDR
            stats['bonus'] +
            0.5 * float(stats['ict_index'])
    )
    print("Overall score = " + str(score))
    return score


def forward_rating(stats, fdr):
    attacking_score = (
            4 * stats['goals_scored'] +
            3 * stats['assists'] +
            3 * stats['expected_goals_per_90'] +
            2 * stats['expected_assists_per_90']
    )
    score = (
            attacking_score * (0.5 * fdr[0] + 1) +  # Apply attacking FDR
            stats['bonus'] +
            0.5 * float(stats['ict_index'])
    )
    return score
