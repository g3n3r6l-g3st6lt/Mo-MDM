#pragma once

#include "CoreMinimal.h"
#include "MazeTypes.h"

class UMazeGrid;
class UMazeConfigAsset;

/**
 * Inputs used to compute spawn/placement decisions for a maze instance.
 * This is intentionally lightweight and algorithmic-only (no UObject lifetime concerns).
 */
struct FMazePlacementInputs
{
    const UMazeGrid* Grid = nullptr;
    const UMazeConfigAsset* ConfigAsset = nullptr;
};

/**
 * Result of placement: where to put start/end, teleporters, and pivotal points.
 * World-space conversion should be performed by the caller (e.g. AMazeActor).
 */
struct FMazePlacementResult
{
    FIntPoint StartCell;
    FIntPoint EndCell;
    TArray<FIntPoint> TeleportInCells;
    TArray<FIntPoint> TeleportOutCells;
    TArray<FIntPoint> PivotalCells;
};

/**
 * High-level helper that decides where to place maze points of interest
 * based on grid topology and configuration rules.
 *
 * NOTE: This is currently only a stub; you can progressively move
 * your existing placement rules here (including "no neighbors near MazeEnd"
 * and "no two TeleportIns/pivots neighboring each other").
 */
namespace MazePlacement
{
    FMazePlacementResult ComputePlacement(const FMazePlacementInputs& Inputs);
}
