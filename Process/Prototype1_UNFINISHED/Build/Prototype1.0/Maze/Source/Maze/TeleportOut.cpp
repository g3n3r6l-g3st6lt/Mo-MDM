#include "TeleportOut.h"

#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"

ATeleportOut::ATeleportOut()
{
    Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    RootComponent = Root;

    Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
    Mesh->SetupAttachment(RootComponent);

    // Visual-only by default; collision handled by the TeleportIn trigger.
    Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);

    PrimaryActorTick.bCanEverTick = false;
}

void ATeleportOut::BeginPlay()
{
    Super::BeginPlay();

    if (Mesh && TeleportMaterial)
    {
        Mesh->SetMaterial(0, TeleportMaterial);
    }
}
