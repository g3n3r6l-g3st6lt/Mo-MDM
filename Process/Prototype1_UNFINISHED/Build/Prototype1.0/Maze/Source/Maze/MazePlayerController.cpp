#include "MazePlayerController.h"
#include "MazeCharacter.h"

#include "EnhancedInputSubsystems.h"
#include "EnhancedInputComponent.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Kismet/GameplayStatics.h"

AMazePlayerController::AMazePlayerController()
{
    bShowMouseCursor = false;
    bEnableClickEvents = false;
    bEnableMouseOverEvents = false;

    PrimaryActorTick.bCanEverTick = true;

    MoveX = 0.f;
    MoveY = 0.f;

    StepTimer = 0.f;
    TimePerHalfStep = 0.3f;

    StepCount = 0;

    PrevDirNorm = FVector2D::ZeroVector;
    bHasPrevDir = false;

    TurnCount = 0;
}

void AMazePlayerController::BeginPlay()
{
    Super::BeginPlay();

    if (ULocalPlayer* LP = GetLocalPlayer())
    {
        if (UEnhancedInputLocalPlayerSubsystem* Subsys =
            ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(LP))
        {
            if (MappingContext)
            {
                Subsys->AddMappingContext(MappingContext, 0);
            }
        }
    }
}

void AMazePlayerController::SetupInputComponent()
{
    Super::SetupInputComponent();

    UEnhancedInputComponent* EIComp = Cast<UEnhancedInputComponent>(InputComponent);
    if (!EIComp)
    {
        return;
    }

    if (IA_MoveForward)
    {
        EIComp->BindAction(
            IA_MoveForward,
            ETriggerEvent::Triggered,
            this,
            &AMazePlayerController::HandleMoveForward
        );
        EIComp->BindAction(
            IA_MoveForward,
            ETriggerEvent::Completed,
            this,
            &AMazePlayerController::HandleMoveForward_Stopped
        );
    }

    if (IA_MoveRight)
    {
        EIComp->BindAction(
            IA_MoveRight,
            ETriggerEvent::Triggered,
            this,
            &AMazePlayerController::HandleMoveRight
        );
        EIComp->BindAction(
            IA_MoveRight,
            ETriggerEvent::Completed,
            this,
            &AMazePlayerController::HandleMoveRight_Stopped
        );
    }
}

void AMazePlayerController::HandleMoveForward(const FInputActionValue& Value)
{
    MoveY = Value.Get<float>();
}

void AMazePlayerController::HandleMoveForward_Stopped(const FInputActionValue& /*Value*/)
{
    MoveY = 0.f;
}

void AMazePlayerController::HandleMoveRight(const FInputActionValue& Value)
{
    MoveX = Value.Get<float>();
}

void AMazePlayerController::HandleMoveRight_Stopped(const FInputActionValue& /*Value*/)
{
    MoveX = 0.f;
}

void AMazePlayerController::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);

    AMazeCharacter* MC = Cast<AMazeCharacter>(GetPawn());
    if (!MC)
    {
        return;
    }

    // build desired move direction from camera yaw
    const FRotator ControlRot = GetControlRotation();
    const float CamYawDeg = ControlRot.Yaw;
    const float CamYawRad = FMath::DegreesToRadians(CamYawDeg);

    const FVector CamForward( FMath::Cos(CamYawRad), FMath::Sin(CamYawRad), 0.f );
    const FVector CamRight(  -FMath::Sin(CamYawRad), FMath::Cos(CamYawRad), 0.f );

    FVector DesiredMoveWorld = (CamRight * MoveX) + (CamForward * MoveY);

    const bool bIsMovingNow = !DesiredMoveWorld.IsNearlyZero();
    if (bIsMovingNow)
    {
        DesiredMoveWorld = DesiredMoveWorld.GetSafeNormal();
    }

    // actually move
    if (bIsMovingNow)
    {
        MC->AddMovementInput(DesiredMoveWorld, 1.f);
    }

    // step counting over time while moving
    if (bIsMovingNow)
    {
        StepTimer += DeltaSeconds;
        while (StepTimer >= TimePerHalfStep)
        {
            StepTimer -= TimePerHalfStep;
            if (!bCountersFrozen) { StepCount += 1; }
        }
    }
    else
    {
        StepTimer = 0.f;
    }

    // turn counting (accepting the "counts extra on corners" behavior you said is OK)
    FVector2D CurDir2D(MoveX, MoveY);

    if (CurDir2D.SizeSquared() > KINDA_SMALL_NUMBER)
    {
        CurDir2D.Normalize();

        if (!bHasPrevDir)
        {
            bHasPrevDir = true;
            PrevDirNorm = CurDir2D;
        }
        else
        {
            const float DotVal = FVector2D::DotProduct(PrevDirNorm, CurDir2D);

            if (DotVal < 0.99f)
            {
                if (!bCountersFrozen) { TurnCount += 1; }
                PrevDirNorm = CurDir2D;
            }
        }
    }
    // else: no input, keep last PrevDirNorm so starting again later can count a turn

    // NOTE: We NO LONGER manually rotate the mesh here.
    // CharacterMovement's bOrientRotationToMovement=true handles facing now.
}
