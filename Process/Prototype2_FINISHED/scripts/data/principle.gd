class_name Principle
extends Resource

@export var id: StringName = &""
@export var name: String = ""
@export var description: String = ""
@export var color: Color = Color.WHITE
@export var loss_message: String = ""

@export var ability_name: String = ""
@export var ability_hint: String = ""
@export var max_charges: int = 2
var charges: int = 0

func refill() -> void:
	charges = max_charges
