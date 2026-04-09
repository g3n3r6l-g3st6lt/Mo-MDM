#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "TeleportIn.generated.h"

class USceneComponent;
class UStaticMeshComponent;
class UBoxComponent;
class UMaterialInterface;

UCLASS()
class MAZE_API ATeleportIn : public AActor
{
    GENERATED_BODY()

public:
    ATeleportIn();

protected:
    virtual void BeginPlay() override;

    UFUNCTION()
    void OnTriggerBegin(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor,
                        UPrimitiveComponent* OtherComp, int32 OtherBodyIndex,
                        bool bFromSweep, const FHitResult& SweepResult);

public:
    UPROPERTY(VisibleAnywhere, Category="Components")
    USceneComponent* Root;

    UPROPERTY(VisibleAnywhere, Category="Components")
    UStaticMeshComponent* Mesh;

    UPROPERTY(VisibleAnywhere, Category="Components")
    UBoxComponent* Trigger;

    UPROPERTY(EditAnywhere, Category="Visual")
    UMaterialInterface* TeleportMaterial;

    UPROPERTY(EditAnywhere, Category="Teleport")
    float TeleportCooldown = 0.25f;
};
