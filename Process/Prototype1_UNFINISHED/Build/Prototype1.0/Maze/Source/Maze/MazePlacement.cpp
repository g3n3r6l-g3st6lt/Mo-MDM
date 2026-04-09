#include "MazePlacement.h"
#include "MazeGrid.h"
#include "MazeConfigAsset.h"

namespace MazePlacement
{
    FMazePlacementResult ComputePlacement(const FMazePlacementInputs& Inputs)
    {
        FMazePlacementResult Result;

        if (!Inputs.Grid || !Inputs.ConfigAsset)
        {
            UE_LOG(LogTemp, Warning, TEXT("MazePlacement::ComputePlacement called with invalid inputs"));
            return Result;
        }

        const FMazeConfig RuntimeConfig = Inputs.ConfigAsset->ToRuntimeConfig();

        // For now, we just mirror the entrance/exit from config.
        Result.StartCell = FIntPoint(RuntimeConfig.EntranceCol, RuntimeConfig.EntranceRow);
        Result.EndCell   = FIntPoint(RuntimeConfig.ExitCol, RuntimeConfig.ExitRow);

        // TODO: move teleporter and pivotal point selection logic here.
        // You can enforce:
        // - No teleporter/pivot neighboring the MazeEnd cell.
        // - No two teleporters/pivots neighboring each other.
        // - Respect MinTeleporters / MaxTeleporters from FMazeTeleporterRuleSettings.

        return Result;
    }
}
