extends Node

signal principles_changed(held_ids: Array)
signal principle_dropped(principle: Principle)
signal threshold_reached(number: int)
signal player_moved(position: Vector2i)
signal maze_needs_refresh()
signal reached_goal()

signal ability_used(principle_id: StringName)
signal ability_failed(reason: String)
signal charges_changed(principle_id: StringName, remaining: int)

signal level_finished(level: int)
signal next_level()
signal back_to_menu()
