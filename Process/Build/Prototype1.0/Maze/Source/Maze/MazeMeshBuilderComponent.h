#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "MazeTypes.h"
#include "MazeMeshBuilderComponent.generated.h"

class UMazeGrid;

/**
 * Component responsible purely for translating a UMazeGrid + FMazeConfig into world meshes.
 * This allows AMazeActor to focus on orchestration rather than mesh spawning details.
 */
UCLASS(ClassGroup=(Maze), meta=(BlueprintSpawnableComponent))
class MAZE_API UMazeMeshBuilderComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UMazeMeshBuilderComponent();

    /** Clears any previously spawned maze meshes (walls, floor, etc.). */
    UFUNCTION(BlueprintCallable, Category = "Maze|Mesh")
    void ClearMazeMeshes();

    /**
     * Builds maze meshes in the world based on the provided grid and config.
     * This is intentionally lightweight here; your existing mesh-building logic
     * can be moved into this function over time.
     */
    UFUNCTION(BlueprintCallable, Category = "Maze|Mesh")
    void BuildMazeMeshes(const UMazeGrid* MazeGrid, const FMazeConfig& Config);
};
