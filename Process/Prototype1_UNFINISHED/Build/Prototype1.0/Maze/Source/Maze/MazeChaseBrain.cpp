#include "MazeChaseBrain.h"
#include "MazeEnd.h"
#include "MazeGrid.h"

FVector UMazeChaseBrain::ComputeNextTarget_Implementation(const AMazeEnd* EndActor,
                                                          const FVector& CurrentLocation,
                                                          const FVector& TargetLocation,
                                                          const UMazeGrid* Grid) const
{
    // Default behaviour: just return the target location. Implementations can override this.
    return TargetLocation;
}

FVector UMazeChaseBrain_Simple::ComputeNextTarget_Implementation(const AMazeEnd* EndActor,
                                                                 const FVector& CurrentLocation,
                                                                 const FVector& TargetLocation,
                                                                 const UMazeGrid* Grid) const
{
    // Simple behaviour: same as base, head straight for the target.
    // You can later add noise, easing, etc. here if desired.
    return TargetLocation;
}
