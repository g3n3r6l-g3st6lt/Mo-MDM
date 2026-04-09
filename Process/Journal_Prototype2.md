# Working Title: The Final Problem (prototype 2 - Godot)

## Week 1

I have been sitting with moral parsimony as a concept for months now. The idea that we should prefer the simplest adequate moral theory. I kept circling back to it because it felt like something you could *feel*, not just argue about. Simplification has a texture. It costs something, even when it works.

I started sketching a maze generator because a maze already begs to simplify the concept of navigation into flow, chokes, and goal. You cannot compute every possible path (when you are inside, when you are a human that does not recognize the maze itself). You pick a heuristic, you commit, you discover what your shortcut cost you. Moral parsimony works exactly this way (at least from what I understand). You choose a small set of principles to navigate situations you have not encountered yet, betting that said principles will be adequate enough to help you navigate.

The first attempt was in Unreal Engine. I wanted 3D space, embodied navigation, the full spatial experience. Within a couple of months I knew that was wrong for this phase. C++ fought me every step of the way, Unreal is too "big" to sketch a game that should not be as technically complex. The maze generation was a nightmare (migrating the logic of Mo's Maze Maker from blender to Unreal was a disaster). The scope unraveled slowly and painfully. I was building a literal engine instead of a game.

I stepped back and wrote down what the game actually needed to do: let the player choose principles, let those principles change the maze, and force the player to drop principles at key moments. Everything else was decoration. The core was about choice and consequence in a constrained world.

Time to start allllll over.

## Week 2

I decided to move to Godot with GDScript, I heard in a class that it is much easier to learn because it builds on Python and pretty easy to read/write. The friction is dropping a bit, there are loads of tutorials relevant to my goals; I could write game logic as game logic instead of wrestling with an engine that wanted me to build architecture before I could think about design.

I am sticking to an isometric view on a block grid, but this time the block grid will be crucial to constrain movement. Each cell is either a floor tile or a wall (cube). The maze generator uses a recursive backtracker on a room grid (I have done this dance before on Blender), then converts to a double-resolution block grid where rooms and corridors are both cells. This was the key insight: instead of tracking walls on edges between cells (which made the old Unreal version unreadable), every wall IS a cell. Simple. Walkable means the cell value is zero (maybe if i could have found a way to do this on Unreal it could have made my life easier).

I defined and chose six moral principles: Harm Reduction, Autonomy, Fairness, Utility, Loyalty, Care. Each one gets a color (morality does have aesthetics too, Nietzsche and stuff). Some walls in the maze are tagged with a principle. If you hold that principle, the wall disappears and you can walk through (the player won't know that entering the level). If you drop it at a threshold, the wall reappears in the principle's color (ta daaaa). That moment of colored walls flooding back into the maze is the best visual in the game makes the maze kinda alive but also pretty). You see what you lost, cute.

## Week 3

Principles as passive path-openers were not enough. The player could drop a principle and feel nothing if they happened to not need those paths. And even though real life moral predicaments can mirror that occasional redundancy, the experience needed mechanical weight.

I gave each principle an active ability (with potential limited number of uses):

- Harm Reduction: Pulse Scan (reveal dead-end corridors)...shamelessly inspired by Daredevil.
- Autonomy: Phase Walk (pass through one wall)
- Fairness: Break Wall (destroy an adjacent wall block). This is a bit similar to Phase Walk...may change.
- Utility: Compass (flash the shortest path to goal)...overkill but let's see.
- Loyalty: Breadcrumbs (toggle visited-path visibility)
- Care: Restore (recharge all other abilities by one)

Now dropping a principle means losing a tool you were relying on (maybe). The player who chose Autonomy for its two phase-walk charges and then has to drop it at a threshold genuinely loses something they were counting on. That is the weight.

The Pulse Scan went through an important iteration. Originally it just highlighted the dead-end cell, a single red cube. I rewired it to trace the entire corridor leading to the dead end and flash the whole thing red. Now it is a genuine scouting tool that saves the player from committing to a long corridor (relatively) that goes nowhere. I got inspired by Daredevil, not only because he is my all-time favorite superhero archetype but because his perceived "flaw" is his weapon, and he always feels guilty (self-lore alert).

## Week 4

Where do you force the player to drop a principle through the threshold markers? Before I did a similar system in Unreal but these collectibles added time to the decreasing timer set against the player to navigate the maze as a way to encourage exploration.

First version: evenly spaced by distance from start. This produced thresholds in random corridors, sometimes in dead ends, sometimes in places the player might never visit. Meaningless.

Second version: at intersection junctions. Rooms with three or more open connections. This is where the player is making a real navigation decision. Why reinvent the wheel? this was the exact logic i used for the Unreal prototype. The threshold forces them to simplify their moral toolkit at precisely the moment they face complexity in the spatial layout. That symmetry between moral and spatial simplification is the conceptual core of the game.

I built five generative levels with increasing complexity. The maze grows from 7x7 rooms to 15x15. Threshold count increases. Later levels reduce the number of principles you start with, by level five, you start with ONE principle and face the most thresholds. The maze is still solvable through base corridors. But the experience of navigating it is stripped bare without principles.

## Week 5

I had a moral dilemma system: text scenarios at nodes in the maze with principle-gated response options. The Collapsed Passage. The Divided Path. The Locked Garden. I wrote eight of them.

I cut all of them.

They were disconnected from the spatial experience. The player stopped moving, read text, clicked a button, and continued. The encounter outcomes (recharge an ability, open a wall) were mechanically useful but the scenarios themselves felt grafted on. I am already struggling with feeling pretentious making this game, this was too on-the-nose. I am alreadys simplifying an eternal problem of the human experience, no use rubbing it in with "trolley problems".

The moral content lives in the principle system (hopefully), the ability tradeoffs, and the threshold decisions. Those are embodied choices. You feel them through gameplay. The encounters were asking the player to think about morality (yuck). The maze was asking them to live it.

## Week 6

The final week was code cleanup. I renamed every variable to something a person would write. `position_on_grid` instead of `grid_pos`. `threshold_spots` instead of `threshold_positions`. `shortcut_chance` instead of `tag_density`. Reading the code should feel like reading a description of the game, not decoding an API.

The game is a playable prototype now. Five levels, six principles with unique abilities, threshold drops at intersection junctions, generative mazes, a menu, a tutorial, and an end screen that reflects back what you kept and what you set down. It is not finished. But it is coherent, and the core loop carries the concept.

I will not pretend i have achieved what i wanted, but I have achieved something. It is a completed game, it communicates (to a degree) what I am trying to say...but it feels like trying to discuss Dostoevsky on Sesame Street. That being said, it is a good seed to build on, Godot is my jam for this, it is so cool to be able to do what I want without severe friction from my authoring tool.

Maybe I can have peace knowing that if nothing, this game will be a nice joke to laugh at in the future when morality does become as overlooked and simplistic as it is depicted here.
