#include "MazeCharacter.h"
#include "Camera/CameraComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "GameFramework/CharacterMovementComponent.h"

AMazeCharacter::AMazeCharacter()
{
    PrimaryActorTick.bCanEverTick = true;

    // --- Camera boom setup (top-down camera with lag) ---
    CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
    CameraBoom->SetupAttachment(RootComponent);

    // Put camera above and angled down
    CameraBoom->TargetArmLength = 800.f;
    CameraBoom->SetRelativeRotation(FRotator(-60.f, 0.f, 0.f));

    // We do NOT want the boom to inherit controller rotation, we just want fixed top-down angle
    CameraBoom->bUsePawnControlRotation = false;

    // Give it lag so camera follows smoothly instead of being glued
    CameraBoom->bEnableCameraLag = true;
    CameraBoom->CameraLagSpeed = 5.f;

    // --- Camera itself ---
    FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
    FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
    FollowCamera->bUsePawnControlRotation = false;

    // --- Movement setup ---
    bUseControllerRotationYaw = false; // controller yaw shouldn't spin the capsule directly

    if (UCharacterMovementComponent* MoveComp = GetCharacterMovement())
    {
        // Let Unreal rotate the character to face its movement direction.
        // This fixes the "moonwalk / wrong anim when strafing" issue.
        MoveComp->bOrientRotationToMovement = true;

        // We don't want controller rotation-to-movement blending,
        // we just want velocity to drive facing.
        MoveComp->bUseControllerDesiredRotation = false;

        // Rotation speed for snapping to new direction
        MoveComp->RotationRate = FRotator(0.f, 720.f, 0.f);

        // Tweak walk speed
        MoveComp->MaxWalkSpeed = 600.f;
    }
}

void AMazeCharacter::BeginPlay()
{
    Super::BeginPlay();
}

void AMazeCharacter::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    // No manual mesh rotation here anymore.
}
