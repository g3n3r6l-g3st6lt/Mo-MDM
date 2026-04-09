extends Node

signal pick_screen(offered: Array, how_many: int)
signal drop_screen(held: Array, how_many: int)
signal done()


func show_pick_screen() -> void:
	var offered: Array = GameState.all_principles.duplicate()
	offered.shuffle()
	if offered.size() > GameState.OFFER_COUNT:
		offered.resize(GameState.OFFER_COUNT)
	pick_screen.emit(offered, GameState.current_config()["picks"])


func confirm_picks(chosen: Array) -> void:
	for p in chosen:
		GameState.pick(p)
	done.emit()


func show_drop_screen() -> void:
	GameState.cross_threshold()
	drop_screen.emit(GameState.held.duplicate(), GameState.DROP_COUNT)


func confirm_drops(chosen: Array) -> void:
	for p in chosen:
		GameState.drop(p)
	MazeEvents.maze_needs_refresh.emit()
	done.emit()
