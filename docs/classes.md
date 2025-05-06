# Classes

### Game:

	teams – Tuple of 2 Team instances, away team first and home team second: (Team, Team)
	away_score – Away team score: int
	home_score – Home team score: int

### Team:

	players – List of 9 Player instances, in batting order: 9*[Player]
	name – Name of the time: string
	pitcher – Current pitcher: Player
	batting_number – Current batter: int 0-8

### Player:

	Attributes:
	
		ba – Batting Average, How likely a batter is to hit the ball: 0.1-0.4
		era – Earned Run Average, How many runs a pitcher gives up per 9 innings: 1-9
		sba – Stolen Base Attempts, How likely a runner is to attempt a steal per pitch: 0-0.2
		sbp – Stolen Base Percent, How likely a runner is to successfully steal: 0-0.8

	Methods:

		static create_player() → Player
		static generate_player() → Player
		at_bat(Player) → int
		steal_attempt(Player) → int
