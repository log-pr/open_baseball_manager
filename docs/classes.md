# Classes

### Game:

	Attributes:

		away_team: Team
		home_team: Team
		away_score: int
		home_score: int
        inning_counter: int
        – Tells current inning as well as if it's the top or bottom (starts at 0 and shows how many half-innings since the first)
		batting_team: Team
		defending_team: Team
        
	Methods:

		static game(away_team: Team, home_team: Team) → Game
		at_bat()
        
### Team:

	Attributes:

		players: 9*[Player]
		– List of 9 Player instances, in batting order:
		name: string
		curr_pitcher: Player
		batting_number – Current batter: int 0-8

	Methods:

		team() → Team

### Player:

	Attributes:
	
		ba: double
		– Batting Average, How often a batter actually hits the ball per at bat
		hit_chance: double (range: 0.1-0.3)
		– How likely a batter is to hit the ball per ball, given it is thrown in the zone
		see_ball_chance: double (0.1-0.7)
		– How likely a batter is to notice a pitch is out of the zone and should not be swung at
		era: double
		– Earned Run Average, How many runs a pitcher gives up per 9 innings on average
		er: 0.01-0.15
		– Error Rate, how often a defending player perdorm an error.
		sba: 0-0.2
		– Stolen Base Attempts, How likely a runner is to attempt a steal per pitch
		sbp: 0-0.8
		– Stolen Base Percent, How likely a runner is to successfully steal

	Methods:

		static player() → Player
		–
		pitch() → Pitch
		–
		swing(pitch: Pitch) → int
		– outputted int tells if it was a strike, foul, hit left infield, hit center infield, hit right infield, hit left outfield, hit center outfield, hit right outfield, or home run
		steal_attempt(pitcher: Player) → int
		– 

### Pitch:

    Attributes:

    Methods:

