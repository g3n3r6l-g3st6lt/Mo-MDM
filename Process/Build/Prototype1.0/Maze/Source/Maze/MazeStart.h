// MazeStart.h

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MazeStart.generated.h"

UCLASS()
class MAZE_API AMazeStart : public AActor
{
    GENERATED_BODY()

public:
    AMazeStart();

protected:
    UPROPERTY(VisibleAnywhere, Category="Components")
    USceneComponent* Root;
};

