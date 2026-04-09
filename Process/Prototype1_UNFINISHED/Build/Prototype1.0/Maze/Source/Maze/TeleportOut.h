#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "TeleportOut.generated.h"

class USceneComponent;
class UStaticMeshComponent;
class UMaterialInterface;

UCLASS()
class MAZE_API ATeleportOut : public AActor
{
    GENERATED_BODY()

public:
    ATeleportOut();

protected:
    virtual void BeginPlay() override;

public:
    UPROPERTY(VisibleAnywhere, Category="Components")
    USceneComponent* Root;

    UPROPERTY(VisibleAnywhere, Category="Components")
    UStaticMeshComponent* Mesh;

    UPROPERTY(EditAnywhere, Category="Visual")
    UMaterialInterface* TeleportMaterial;
};
