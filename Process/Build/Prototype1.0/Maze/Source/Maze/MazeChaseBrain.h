#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "MazeChaseBrain.generated.h"

class AMazeEnd;
class UMazeGrid;

/**
 * Base class for pluggable chase strategies used by AMazeEnd.
 * Different implementations can chase directly, follow the grid, use NavMesh, etc.
 */
UCLASS(Abstract, Blueprintable, EditInlineNew, DefaultToInstanced)
class MAZE_API UMazeChaseBrain : public UObject
{
    GENERATED_BODY()

public:
    /**
     * Compute the next target location for the MazeEnd to move toward.
     * @param EndActor          The MazeEnd actor performing the chase.
     * @param CurrentLocation   Current world location of the MazeEnd.
     * @param TargetLocation    World location the MazeEnd is ultimately trying to reach (e.g. start).
     * @param Grid              Optional maze grid for topology-aware strategies.
     */
    UFUNCTION(BlueprintNativeEvent, Category = "Maze|Chase")
    FVector ComputeNextTarget(const AMazeEnd* EndActor,
                              const FVector& CurrentLocation,
                              const FVector& TargetLocation,
                              const UMazeGrid* Grid) const;
    virtual FVector ComputeNextTarget_Implementation(const AMazeEnd* EndActor,
                                                     const FVector& CurrentLocation,
                                                     const FVector& TargetLocation,
                                                     const UMazeGrid* Grid) const;
};

/**
 * Simple chase brain: always heads straight for the target location in a straight line.
 * This matches the current behaviour of MazeEnd and can be extended later.
 */
UCLASS(Blueprintable, EditInlineNew)
class MAZE_API UMazeChaseBrain_Simple : public UMazeChaseBrain
{
    GENERATED_BODY()

public:
    virtual FVector ComputeNextTarget_Implementation(const AMazeEnd* EndActor,
                                                     const FVector& CurrentLocation,
                                                     const FVector& TargetLocation,
                                                     const UMazeGrid* Grid) const override;
};
