#include "MazeMeshBuilderComponent.h"
#include "GameFramework/Actor.h"
#include "MazeGrid.h"

UMazeMeshBuilderComponent::UMazeMeshBuilderComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UMazeMeshBuilderComponent::ClearMazeMeshes()
{
    // Intentionally left blank for now.
    // Move your existing "destroy / clear maze mesh components" logic here.
}

void UMazeMeshBuilderComponent::BuildMazeMeshes(const UMazeGrid* MazeGrid, const FMazeConfig& Config)
{
    if (!MazeGrid)
    {
        UE_LOG(LogTemp, Warning, TEXT("UMazeMeshBuilderComponent::BuildMazeMeshes called with null MazeGrid"));
        return;
    }

    // TODO: Move your existing AMazeActor wall/floor mesh spawning code into this function.
    // Keeping this body small and safe for now.
}
