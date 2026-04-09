extends Camera2D

var target: Node2D = null
var speed: float = 5.0

func _ready() -> void:
	zoom = Vector2(2.0, 2.0)

func follow(node: Node2D) -> void:
	target = node
	if target:
		position = target.position

func _process(delta: float) -> void:
	if target:
		position = position.lerp(target.position, speed * delta)
