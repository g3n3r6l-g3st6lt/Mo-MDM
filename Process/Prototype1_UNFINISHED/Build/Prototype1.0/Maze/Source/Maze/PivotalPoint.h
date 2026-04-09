#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "PivotalPoint.generated.h"

UCLASS()
class MAZE_API APivotalPoint : public AActor
{
    GENERATED_BODY()
public:
    APivotalPoint();
    virtual void Tick(float DeltaSeconds) override;

protected:
    UPROPERTY(VisibleAnywhere, Category="Components") USceneComponent* Root;
    UPROPERTY(VisibleAnywhere, Category="Components") UStaticMeshComponent* Sphere;
    UPROPERTY(VisibleAnywhere, Category="Components") class USphereComponent* Trigger;

public:
    UPROPERTY(EditAnywhere, Category="Visual") UStaticMesh* SphereMesh=nullptr;
    UPROPERTY(EditAnywhere, Category="Visual") UMaterialInterface* EmissiveMaterial=nullptr;
    UPROPERTY(EditAnywhere, Category="Visual") UMaterialInterface* ActivatedMaterial=nullptr;
    UPROPERTY(EditAnywhere, Category="Visual") float GlowIntensity=20.f;
    UPROPERTY(EditAnywhere, Category="Audio") class USoundBase* ActivateSound=nullptr;

    UPROPERTY(VisibleAnywhere, Category="State") bool bActivated=false;
    UPROPERTY(VisibleAnywhere, Category="State") bool bDisintegrating=false;
    float DisintegrateTime=0.f;

    virtual void OnConstruction(const FTransform& Transform) override;

    UFUNCTION()
    void OnTriggerBegin(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor,
                        UPrimitiveComponent* OtherComp, int32 OtherBodyIndex,
                        bool bFromSweep, const FHitResult& SweepResult);
};
