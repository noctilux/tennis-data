from datetime import datetime

from tdata.datasets.score import Score
from tdata.enums.surface import Surfaces
from tdata.enums.t_type import (Tours, is_singles, is_standard_doubles,
                                is_mixed_doubles)
from tdata.scrapers.utils import (load_json_url, fetch_logger, prettify_json,
                                  load_html_page)


logger = fetch_logger(__name__, 'sofa_score.log')


class SofaScoreScraper(object):

    def __init__(self, t_type=Tours.atp):

        self.base_url = 'https://www.sofascore.com'

        self.surface_lookup = {
            'Hardcourt indoor': Surfaces.indoor_hard,
            'Clay': Surfaces.clay
        }

        if t_type != Tours.atp:
            raise Exception('Only ATP supported for now!')

    @property
    def season_ids(self):

        # These could be scraped, but manually state them for now.
        # TODO: Maybe use beautifulsoup to scrape instead.
        season_ids = {
            2018: 15801,
            2017: 12805,
            2016: 11183,
            2015: 11172,
            2014: 11182,
            2013: 11187,
            2012: 11195,
            2011: 11189,
            2010: 11196,
            2009: 11192
        }

        return season_ids

    @property
    def tournament_pages(self):
        # FIXME: These could maybe be found somehow rather than magic-ed
        # Also, there are more -- for challengers etc...
        pages = {Tours.atp: '/esi/category/3/tournaments?_=152826353',
                 Tours.wta: '/esi/category/6/tournaments?_=152826440'}

        # Doubles are on the same page
        pages[Tours.atp_doubles] = pages[Tours.atp]
        pages[Tours.wta_doubles] = pages[Tours.wta]

        # I believe mixed is listed under ATP
        pages[Tours.mixed_doubles] = pages[Tours.atp]

        return pages

    @staticmethod
    def parse_tournament_html(url, t_type):

        soup = load_html_page(url)
        all_links = soup.find_all('a')

        links = [x.get('href') for x in all_links]
        names = [x.get_text().strip() for x in all_links]
        lookup = {x: y for x, y in zip(names, links)}

        if is_singles(t_type):
            # This is a singles event -- discard doubles
            lookup = {x: y for x, y in lookup.items() if 'Doubles' not in x}
        elif is_standard_doubles(t_type):
            lookup = {x: y for x, y in lookup.items() if 'Doubles' in x and
                      'Mixed' not in x}
        elif is_mixed_doubles(t_type):
            lookup = {x: y for x, y in lookup.items() if 'Mixed' in x}
        else:
            raise ValueError('Unknown tournament type')

        return lookup

    def get_tournament_list(self, t_type=Tours.atp, discard_doubles=True):

        subpage = self.tournament_pages[t_type]
        full_url = self.base_url + subpage
        logger.debug('Fetching tournament list...')
        lookup = self.parse_tournament_html(full_url, t_type)
        logger.debug('Fetched tournament list.')
        return lookup

    def find_surface(self, tournament_json):

        t_info = tournament_json['tournamentInfo']['tennisTournamentInfo']

        surface_entry = [
            x['value'] for x in t_info if x['name'] == 'Ground type']

        assert(len(surface_entry) == 1)

        surface = self.surface_lookup[surface_entry[0]]

        return surface

    def get_tournament_info(self, tournament_link, year):

        tournament_id = tournament_link.split('/')[-1]

        # Look up the season id
        season_id = self.season_ids[year]

        # Put together the link
        subpage = '/u-tournament/{}/season/{}/json'.format(
            tournament_id, season_id)

        full_url = self.base_url + subpage

        # Fetch the json
        json_data = load_json_url(full_url)

        # Extract match events
        team_events = json_data['teamEvents']

        # Flatten the events
        matches = [team_events[y][x] for y in team_events for x in
                   team_events[y]]

        # FIXME: These don't seem to be complete
        match_ids = set([x['total'][0]['id'] for x in matches])

        surface = self.find_surface(json_data)

        return match_ids

    @staticmethod
    def to_score(winner_dict, loser_dict, winner_name, loser_name):

        # TODO: Think about retirements.

        # Find the periods
        periods = [x for x in winner_dict if 'period' in x
                   and 'TieBreak' not in x]

        set_scores = list()

        for cur_period in periods:

            tb_key = cur_period + 'TieBreak'

            set_score = '{}-{}'.format(winner_dict[cur_period],
                                       loser_dict[cur_period])

            if tb_key in winner_dict:

                winner_score = winner_dict[tb_key]
                loser_score = loser_dict[tb_key]
                tb_score = (winner_score if winner_score < loser_score else
                            loser_score)
                set_score += '({})'.format(tb_score)

            set_scores.append(set_score)

        full_score = ' '.join(set_scores)

        return Score(full_score, winner_name, loser_name)

    @staticmethod
    def extract_match_data(match_json_data):

        # TODO: Add surface; return a CompletedMatch.
        # Later: Add stats.
        # Also: look into making a surface enum, and stuff like that.
        event_details = match_json_data['event']

        # Let's find winner and loser
        home = event_details['homeTeam']
        away = event_details['awayTeam']

        home_id = home['id']
        away_id = away['id']

        # This seems to be an abbreviated name. Maybe get the full name from
        # elsewhere.
        home_name = home['name']
        away_name = away['name']

        # Not sure -- check this
        home_won = event_details['winnerCode'] == 1
        winner = home_name if home_won else away_name
        loser = home_name if not home_won else away_name
        match_date = datetime.fromtimestamp(event_details['startTimestamp'])

        # Extract the score
        away_score = event_details['awayScore']
        home_score = event_details['homeScore']

        winner_score = home_score if home_won else away_score
        loser_score = away_score if home_won else home_score

        score = SofaScoreScraper.to_score(winner_score, loser_score, winner,
                                          loser)

    def get_match_data_from_id(self, match_id):

        subpage = '/event/{}/json'.format(match_id)
        full_url = self.base_url + subpage
        json_data = load_json_url(full_url)
        self.extract_match_summary(json_data)
        return json_data

    def parse_tournament(self, tournament_link, year):

        # Get match ids
        match_ids = self.get_match_ids(tournament_link, year)
        match_data = [self.get_match_data_from_id(x) for x in match_ids]
        return match_data

if __name__ == '__main__':

    scraper = SofaScoreScraper()
    t_list = scraper.get_tournament_list()
    print(scraper.get_tournament_info(t_list.items()[2][1], 2017))
