#include "PivotalPoint.h"
#include "Components/StaticMeshComponent.h"
#include "Components/SphereComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Kismet/GameplayStatics.h"
#include "MazeGameMode.h"

APivotalPoint::APivotalPoint()
{
    PrimaryActorTick.bCanEverTick = true;
    Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    SetRootComponent(Root);

    Sphere = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Sphere"));
    Sphere->SetupAttachment(RootComponent);
    Sphere->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Sphere->SetCastShadow(false);
    Sphere->bCastDynamicShadow = false;
    Sphere->SetRenderCustomDepth(true);
    Sphere->SetCustomDepthStencilValue(1);
    Sphere->SetRelativeScale3D(FVector(0.6f));

    Trigger = CreateDefaultSubobject<USphereComponent>(TEXT("Trigger"));
    Trigger->InitSphereRadius(60.f);
    Trigger->SetupAttachment(RootComponent);
    Trigger->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
    Trigger->SetCollisionResponseToAllChannels(ECollisionResponse::ECR_Ignore);
    Trigger->SetCollisionResponseToChannel(ECC_Pawn, ECollisionResponse::ECR_Overlap);
    Trigger->OnComponentBeginOverlap.AddDynamic(this, &APivotalPoint::OnTriggerBegin);
}

void APivotalPoint::OnConstruction(const FTransform&)
{
    if (Sphere && SphereMesh) Sphere->SetStaticMesh(SphereMesh);
    if (Sphere && EmissiveMaterial)
    {
        UMaterialInstanceDynamic* MID = Sphere->CreateAndSetMaterialInstanceDynamicFromMaterial(0, EmissiveMaterial);
        if (MID) MID->SetScalarParameterValue(TEXT("GlowIntensity"), GlowIntensity);
    }
}

void APivotalPoint::OnTriggerBegin(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor,
                                   UPrimitiveComponent* OtherComp, int32 OtherBodyIndex, bool bFromSweep, const FHitResult& SweepResult)
{
    if (bActivated || !OtherActor) return;
    if (!OtherActor->IsA(APawn::StaticClass())) return;

    bActivated = true;
    bDisintegrating = true;
    DisintegrateTime = 0.f;

    if (Sphere && ActivatedMaterial) Sphere->SetMaterial(0, ActivatedMaterial);
    if (ActivateSound) UGameplayStatics::PlaySoundAtLocation(this, ActivateSound, GetActorLocation());

    if (AMazeGameMode* GM = GetWorld() ? GetWorld()->GetAuthGameMode<AMazeGameMode>() : nullptr)
    {
        GM->IncrementPivotalPointsActivated();
        if (GM->CountdownSeconds > 0)
        {
            GM->CountdownSeconds += 5; // +5 seconds per pivotal point collected
        }
    }

    if (Trigger) Trigger->SetCollisionEnabled(ECollisionEnabled::NoCollision);
}

void APivotalPoint::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    if (bDisintegrating)
    {
        DisintegrateTime += DeltaSeconds;
        const float Scale = FMath::Lerp(1.f, 0.f, FMath::Clamp(DisintegrateTime/0.5f, 0.f, 1.f));
        SetActorScale3D(FVector(Scale));
        if (DisintegrateTime >= 0.5f) { Destroy(); }
    }
}
