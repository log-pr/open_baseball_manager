# Classes

### Game:

    Attributes:

        away_team: Team
        home_team: Team
        away_score: int
        home_score: int
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
	
		ba: 0.1-0.4
        – Batting Average, How likely a batter is to hit the ball
		era: int 1-9
        – Earned Run Average, How many runs a pitcher gives up per 9 innings
        er: 0.01-0.15
        – Error Rate, how often a defending player perdorm an error.
		sba: 0-0.2
        – Stolen Base Attempts, How likely a runner is to attempt a steal per pitch
		sbp: 0-0.8
        – Stolen Base Percent, How likely a runner is to successfully steal

	Methods:

		static player() → Player
		pitch() → Pitch
        swing(pitch: Pitch) → double
		steal_attempt(pitcher: Player) → int
