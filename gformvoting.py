import argparse

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns


# -- Loading and preparation of a .csv
def load_voting(filepath):
    """Load and prepare an election .csv
    The column headers are kept in their orignal form

    :param filepath: Path to .csv output of the Google Form
    :type filepath: str
    :return: mastertable, roles, candidates
    :rtype: pd.DataFrame, list, list
    """
    mastertable = pd.read_csv(filepath)

    mastertable = remove_non_vote_columns(mastertable)
    mastertable = mastertable.applymap(voting_value_to_num)

    roles, candidates = find_roles_and_candidates(mastertable)
    return mastertable, roles, candidates


def remove_non_vote_columns(mastertable):
    """Removes columns that aren't MultiChoiceGrid columns..
    This assumes that only election questions end with ']'

    :param mastertable:
    :type mastertable: pd.DataFrame
    :return:
    :rtype: pd.DataFrame
    """
    killcolumns = [columnname for columnname in mastertable.keys() if columnname[-1] != ']']
    return mastertable.drop(columns=killcolumns)


def voting_value_to_num(contents):
    """Convert the form's P1/P2/P3... into integers.
    If a column contains a vote where no preference was specified, then the votes will be in float form
    since pandas can't put nans into integer type columns.

    :param contents:
    :type contents: a value from a cell
    :return: Value representing the vote, no preference is a zero
    :rtype: int or np.nan
    """
    if not isinstance(contents, str):
        return np.nan
    else:
        return int(contents[1:])


def split_columnname(columnname):
    """Find the role and the name of a candidate from the column header
    The form's header format should be like:
    Albert Einstein [Sports Representative]

    :param columnname: Name of the column as direct from the Form
    :type columnname: str
    :return: role, name
    :rtype: Tuple
    """
    role, name = columnname.split(' [')
    name = name[:-1]  # Remove the final ']'
    return role, name


def find_roles_and_candidates(mastertable):
    """Find all roles and all candidates in the master vote table

    :param mastertable:
    :type mastertable: pd.DataFrame
    :return: lists of roles, names
    :rtype: Tuple
    """
    roles = []
    names = []
    for col in mastertable.keys():
        role, name = split_columnname(col)
        if role not in roles:
            roles.append(role)
        if name not in names:
            names.append(name)
    names.sort()
    return roles, names


# -- Prepare the counting for a single role/seat in the election
def retrieve_role_voting_table(mastertable, rolename):
    """Extract a table relating to a single role
    Columns are renamed to the name of the candidate

    :param mastertable:
    :type mastertable: pd.DataFrame
    :param rolename: Name of role
    :type rolename: str
    :return: Table with only the columns for a particular role, with the columns renamed to the candidate name.
    :rtype: pd.DataFrame
    """
    election_columns = [rolename == split_columnname(columnname)[0] for columnname in mastertable.keys()]
    assert sum(election_columns) > 0, f"{rolename} not found as a role in the master table."
    voting_table = mastertable.loc[:, election_columns]
    voting_table = voting_table.rename(
        columns=dict([(colname, split_columnname(colname)[1]) for colname in voting_table.keys()]))
    return voting_table


def discard_informal_votes(voting_table):
    """Remove rows that have informal votes

    :param voting_table: should be the output of retrieve_role_voting_table()
    :type voting_table: pd.DataFrame
    :return: A possibly shorter len() table
    :rtype: pd.DataFrame
    """
    invalids = []
    for index, vote in voting_table.iterrows():
        no_vote = [np.isnan(pref) for pref in vote]
        if all(no_vote):
            invalids.append(index)
            continue
        no_first_pref = not any(vote == 1)
        not_sequential = not all([sum(vote.isin([float(pref)])) == 1 for pref in range(1, int(vote.max()) + 1)])
        if no_first_pref or not_sequential:
            invalids.append(index)
    print(f"Removed {len(invalids)} informal votes of {len(voting_table)}.")
    return voting_table.drop(invalids)


def remove_excluded_candidates(voting_table, excluded):
    """Remove columns with votes for excluded candidates

    :param voting_table:
    :type voting_table: pd.DataFrame
    :param excluded: List of candidate names to exclude
    :type excluded: list
    :return: voting_table with columns of excluded removed
    :rtype: pd.DataFrame
    """
    for candidate in excluded:
        assert candidate in voting_table.keys(), f"{candidate} is not in the voting table, check spelling."
    voting_table = voting_table.drop(columns=excluded)
    return voting_table

def find_lowest_candidates(resulttable):
    """Find the candidates with the lowest total

    :param resulttable: Output of a ElectionManager.calculate_total, columns of Candidate and Total
    :type resulttable: pd.DataFrame
    :return: List of names of the candidates with the lowest score
    :rtype: list
    """
    mintotal = resulttable.Total.min()
    lowest = resulttable.Total == mintotal
    candidates = resulttable.loc[lowest, 'Candidate'].values.tolist()
    return candidates


class ElectionManager:
    def __init__(self, votetable, n_winners=1, doplot=False):
        """Manages elections and keep records.

        :param votetable: Output of retrieve_role_voting_table()
        :type votetable: pd.DataFrame
        :param n_winners: Number of seats/positions available for this role.
        :type n_winners: int
        :param doplot: Plot a bar chart showing result for each round
        :type doplot: bool or plt.Axes
        """
        self.votes = [Vote(row) for index, row in votetable.iterrows()]

        self.n_winners = n_winners
        self.quota = np.floor(len(votetable) / (n_winners + 1)) + 1  # minimum number of votes required to win

        self.candidates = votetable.keys().to_list()
        self.remaining_candidates = votetable.keys().to_list()
        self.winning_candidates = []
        self.result_record = []

        self.allow_random_tiebreak = False
        self.verbose = True
        self.doplot = doplot

    def run(self):
        print(f"Running election with candidates {self.candidates}")
        for round in range(1, len(self.candidates) + 1):
            print(f"Round {round}")
            result = self.calculate_total(self.remaining_candidates)
            result['Round'] = round
            self.result_record.append(result)

            winning = result.Total >= self.quota
            if any(winning):
                winning_candidates = result.loc[winning, 'Candidate'].values
                [self.winning_candidates.append(candidate) for candidate in winning_candidates]
                if len(self.winning_candidates) == self.n_winners:
                    break
                elif len(self.winning_candidates) < self.n_winners:
                    # If the required number of winners haven't been found, we'll have to transfer
                    for candidate in winning_candidates:
                        total_value = result.loc[result.Candidate == candidate, 'Total'].value
                        surplus_votes = total_value - self.quota
                        transfer_value = surplus_votes / total_value
                        for vote in self.votes:
                            if vote.voting_for(self.remaining_candidates) == candidate:
                                vote.value = vote.value * transfer_value
                    [self.remaining_candidates.remove(candidate) for candidate in winning_candidates]
                else:
                    raise AssertionError("More winners than allowed, this should be impossible.")

            eliminated_candidate_list = find_lowest_candidates(result)
            if len(eliminated_candidate_list) > 1:
                print('Tiebreak initiated!')
                eliminated_candidate = self.tiebreak(eliminated_candidate_list)
            elif len(eliminated_candidate_list) == 0:
                raise AssertionError("This shouldn't be possible")
            else:
                eliminated_candidate = eliminated_candidate_list[0]
            self.remaining_candidates.remove(eliminated_candidate)
            if self.verbose:
                print(f"{eliminated_candidate} eliminated.")

        print(f"Winners: {', '.join(self.winning_candidates)}")
        if self.doplot:
            result_record = pd.concat(self.result_record)
            ax = plt.gca()
            sns.barplot(ax=ax, data=result_record, x='Round', y='Total', hue='Candidate')
            ax.axhline(self.quota, c='r', ls='--')
            ax.legend(loc=(1.01, 0))

    def calculate_total(self, candidates):
        """Find how many votes each candidate in candidates is receiving.
        This takes into account the value of the vote (which can decrease in STV)

        :param candidates: List of candidates to find a total for
        :type candidates: list
        :return: Table with columns candidate and total, of len() len(candidates)
        :rtype: pd.DataFrame
        """
        vote_table = []
        for vote in self.votes:
            vote_table.append({'Candidate': vote.voting_for(candidates),
                               'Value': vote.value})  # value can be lower than one if it's been transferred from winner
        vote_table = pd.DataFrame(vote_table)

        result = []
        for candidate in candidates:
            result.append({'Candidate': candidate,
                           'Total': vote_table.loc[vote_table.Candidate == candidate, 'Value'].sum()})
        result = pd.DataFrame(result)
        return result

    def tiebreak(self, tied_candidates):
        """Use tiebreak algorithm to find candidate to eliminate.

        First use Backwards Tie-Breaking, then use Raw Preference if that fails.

        :param tied_candidates:
        :type tied_candidates: list
        :return: Name of eliminated candidate
        :rtype: str
        """
        eliminated = self.backwards_tiebreak(tied_candidates)
        if eliminated is None:
            eliminated = self.preference_tiebreak(tied_candidates)
        return eliminated

    def backwards_tiebreak(self, tied_candidates):
        """Break tie by looking to previous rounds for the difference"""
        result_record = pd.concat(self.result_record)
        result_record = result_record.loc[result_record['Candidate'].isin(tied_candidates)]  # Only tied_candidates
        for round in np.sort(result_record['Round'].unique())[::-1]:  # Iterate from most recent to first round
            result = result_record.loc[result_record['Round'] == round, :]
            eliminated = find_lowest_candidates(result)
            if len(eliminated) == 1:
                if self.verbose:
                    print(f"\tLookback tiebreak finds difference at round {round}")
                return eliminated[0]
            else:
                continue
        if self.verbose:
            print("\tBackwards tiebreak failed.")
        return None

    def preference_tiebreak(self, tied_candidates):
        """Resolve a situation where multiple candidates received the least amount of first preferences

        :param tied_candidates: Candidates who are tied for lowest first place
        :type tied_candidates: list
        :return: The unlucky candidate's name
        :rtype: str
        """

        # Find the votes that are involved in the tie in the current round
        active_votes = [vote for vote in self.votes if vote.voting_for(self.remaining_candidates) in tied_candidates]
        result_record = []
        for pref in range(1, len(self.candidates)):  # Maximum preference # is len(candidates)
            votetable = []
            # Build a table of raw preferences (i.e. without transfer)
            for vote in active_votes:
                votetable.append({'Candidate': vote.voting_for(self.candidates,
                                                               preference=pref),  # For this level of preference
                                  'Value': vote.value})
            votetable = pd.DataFrame(votetable)

            # Find the results for our candidates of interest
            result = pd.DataFrame([{'Candidate': candidate,
                                    'Total': votetable.loc[votetable.Candidate == candidate, 'Value'].sum()}
                                   for candidate in tied_candidates])
            result['Preference'] = pref
            result_record.append(result)
            mintotal = result.Total.min()
            lowest = result.Total == mintotal
            if sum(lowest) == 1:
                result_record = pd.concat(result_record)
                if self.verbose:
                    print(f"\tPreference tiebreaker finds difference at preference level: {pref}")
                return result.loc[lowest, 'Candidate'].item()
        result_record = pd.concat(result_record)
        if self.allow_random_tiebreak:
            print("Holy moly! It's a tie all the way down, initiating a random tiebreak!")
            return np.random.choice(result.loc[lowest, 'Candidate'].values)
        else:
            raise AssertionError(f"We've got a total tie and random solutions aren't allowed!")


class Vote:
    def __init__(self, voterow):
        """A single vote

        :param voterow: A row from retrieve_role_voting_table()
        :type voterow: pd.Series
        """
        self.vote = voterow
        self.value = 1  # This can change if the vote is transferred following a surplus

    def voting_for(self, valid_candidates, preference=1):
        """Given a list of candidates, which one does this vote go to?

        :param valid_candidates: List of candidates that the vote could go to
        :type valid_candidates: list
        :param preference: Which preference to find
        :type preference: int
        :return: Name of candidate that the vote is going to
        :rtype: str
        """
        active_vote = self.vote[valid_candidates]
        active_vote = active_vote.loc[~active_vote.isna()]  # remove nans
        pointing_to = active_vote.argsort().argsort()  # raw preferences into ranked list
        requested_preference = pointing_to == (preference - 1)  # 1st preference is sorted to 0
        if sum(requested_preference) == 0:
            return None
        return pointing_to.keys()[requested_preference].item()


def main(filepath, show_plot=False):
    master_voting_table, roles, names = load_voting(filepath)
    print(f"Unique roles found: {roles}")
    print(f"Unique candidates found: {names}")

    if show_plot:
        plt.clf()
        grid = plt.GridSpec(len(roles), 2, width_ratios=[6, 1])
    for xrole, role in enumerate(roles):
        print(" ")
        print(f"Role: {role}")
        election_table = retrieve_role_voting_table(master_voting_table, role)
        manager = ElectionManager(election_table, doplot=plt.subplot(grid[xrole, 0]) if show_plot else show_plot)
        manager.run()

    if show_plot:
        plt.show()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("fpath")
    parser.add_argument('-r', '--role',
                        default='all')
    parser.add_argument('-s', '--seats',
                        type=int, default=1)
    parser.add_argument('-e', '--exclude',
                        nargs='+', default=[])

    return parser.parse_args()


# %%
if __name__ == '__main__':
    args = parse_args()
    if args.role == 'all':
        main(args.fpath)
    else:
        master_voting_table, roles, names = load_voting(args.fpath)
        election_table = retrieve_role_voting_table(master_voting_table, args.role)
        election_table = remove_excluded_candidates(election_table, args.exclude)
        manager = ElectionManager(election_table, n_winners=args.seats)
        manager.run()
