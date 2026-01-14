#include "MazeHUD.h"
#include "MazeGameMode.h"
#include "MazePlayerController.h"
#include "MazeActor.h"
#include "MazeStart.h"
#include "MazeEnd.h"
#include "TeleportIn.h"
#include "Blueprint/UserWidget.h"


#include "Engine/Canvas.h"
#include "Engine/Font.h"
#include "Kismet/GameplayStatics.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"

AMazeHUD::AMazeHUD()
{
    TextScale = 1.2f;
    BackgroundAlpha = 0.35f;
    BackgroundPadding = FVector2D(16.f, 12.f);
}


void AMazeHUD::BeginPlay()
{
    Super::BeginPlay();

    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    // Cache maze actor and bounds for the canvas-drawn minimap.
    AMazeActor* MazeActor = nullptr;
    {
        TArray<AActor*> MazeActors;
        UGameplayStatics::GetAllActorsOfClass(World, AMazeActor::StaticClass(), MazeActors);
        if (MazeActors.Num() > 0)
        {
            MazeActor = Cast<AMazeActor>(MazeActors[0]);
        }
    }

    FVector2D MazeMin(-1000.f, -1000.f);
    FVector2D MazeMax(1000.f, 1000.f);

    if (MazeActor)
    {
        MazeActor->GetMazeWorldBounds2D(MazeMin, MazeMax);
    }

    MazeWorldMin = MazeMin;
    MazeWorldMax = MazeMax;

    // Cache TeleportIn actors for the minimap.
    TeleportInActorsCached.Reset();
    {
        TArray<AActor*> Found;
        UGameplayStatics::GetAllActorsOfClass(World, ATeleportIn::StaticClass(), Found);
        TeleportInActorsCached = Found;
    }
}
static float ProgressPercentAlongSegmentXY(const FVector& Start, const FVector& End, const FVector& Pos)
{
    const FVector2D A(Start.X, Start.Y);
    const FVector2D B(End.X,   End.Y);
    const FVector2D P(Pos.X,   Pos.Y);

    const FVector2D AB = B - A;
    const float Den = FVector2D::DotProduct(AB, AB);
    if (Den <= KINDA_SMALL_NUMBER) return 0.f;

    const float T = FMath::Clamp( FVector2D::DotProduct(P - A, AB) / Den, 0.f, 1.f );
    return T * 100.f;
}

void AMazeHUD::DrawHUD()
{
    Super::DrawHUD();
    if (!HudFont) return;

    UWorld* World = GetWorld();
    if (!World) return;

    APlayerController* PC = GetOwningPlayerController();
    if (!PC) PC = UGameplayStatics::GetPlayerController(World, 0);
    if (!PC) return;

    APawn* Pawn = PC->GetPawn();
    if (!Pawn) return;

    int32 StepsLive = 0, TurnsLive = 0;
    if (auto* MPC = Cast<AMazePlayerController>(PC))
    {
        StepsLive = MPC->GetStepCount();
        TurnsLive = MPC->GetTurnCount();
    }
    
    const bool bMovedThisFrame  = (StepsLive != PrevStepCount);
    const bool bTurnedThisFrame = (TurnsLive != PrevTurnCount);
    PrevStepCount = StepsLive;
    PrevTurnCount = TurnsLive;

    const bool bHasVelocity = !Pawn->GetVelocity().IsNearlyZero(1.0f);
    // consider moving if there is velocity OR a step happened OR a turn happened this frame
    const bool bMovingOrTurning = bHasVelocity || bMovedThisFrame || bTurnedThisFrame;

    AMazeGameMode* GM = Cast<AMazeGameMode>(UGameplayStatics::GetGameMode(World));
    const FVector StartLoc = GM ? GM->GetStartLocation() : FVector::ZeroVector;
    const FVector EndLoc   = GM ? GM->GetEndLocation()   : FVector::ZeroVector;
        const float ProgressPct = ProgressPercentAlongSegmentXY(StartLoc, EndLoc, Pawn->GetActorLocation());
    const float TimeRemain = GM ? GM->GetTimeRemaining() : TNumericLimits<float>::Max();
    const bool bExpired = GM ? GM->IsTimeExpired() : false;

    // Freeze progress percentage once the run has finished (e.g., goal reached).
    const bool bHasFinished = GM ? GM->GetHasFinished() : false;
    if (bHasFinished && !bProgressFrozen)
    {
        FrozenProgressPct = ProgressPct;
        bProgressFrozen = true;
    }

    const float EffectiveProgressPct = bProgressFrozen ? FrozenProgressPct : ProgressPct;
    // Freeze pivotal point counts once the run has finished as well.
    const int32 PivotsActivatedLive = GM ? GM->GetNumPivotalPointsActivated() : 0;
    const int32 PivotsTotalLive     = GM ? GM->GetNumPivotalPointsTotal()     : 0;
    if (bHasFinished && !bPivotsFrozen)
    {
        FrozenPivotalActivated = PivotsActivatedLive;
        FrozenPivotalTotal     = PivotsTotalLive;
        bPivotsFrozen          = true;
    }
    else if (!bHasFinished)
    {
        bPivotsFrozen = false;
    }
    const int32 PivotsActivatedDisplay = bPivotsFrozen ? FrozenPivotalActivated : PivotsActivatedLive;
    const int32 PivotsTotalDisplay     = bPivotsFrozen ? FrozenPivotalTotal     : PivotsTotalLive;


    FString StatusText = TEXT("Stationary");
FLinearColor StatusColor = FLinearColor::White;

if (GM && GM->GetHasFinished())
{
    const FName FinishStatus = GM->GetFinishStatus();
    if (FinishStatus == FName(TEXT("ElusiveSave")))
    {
        StatusText = TEXT("Elusive Save");
        StatusColor = FLinearColor(0.4f, 0.8f, 1.f, 1.f);
    }
    else if (FinishStatus == FName(TEXT("Singularity")))
    {
        StatusText = TEXT("Singularity");
        StatusColor = FLinearColor(0.9f, 0.3f, 1.f, 1.f);
    }
    else
    {
        StatusText = TEXT("Goal Reached");
        StatusColor = FLinearColor(1.f, 0.85f, 0.1f, 1.f);
    }
}
else if (bExpired)
{
    StatusText = TEXT("Wasteful");
    StatusColor = FLinearColor(1.f, 0.25f, 0.25f, 1.f);
}
else if (bMovingOrTurning)
{
    StatusText = TEXT("Running");
    StatusColor = FLinearColor(0.1f, 0.9f, 0.2f, 1.f);
}
// else stays "Stationary"

        TArray<FString> Lines;
    Lines.Add(FString::Printf(TEXT("Steps: %d  Turns: %d"), StepsLive, TurnsLive));
    Lines.Add(FString::Printf(TEXT("Progress: %d%%"), FMath::RoundToInt(EffectiveProgressPct)));
    if (TimeRemain != TNumericLimits<float>::Max())
    {
        Lines.Add(FString::Printf(TEXT("Time: %ds"), FMath::Max(0, FMath::FloorToInt(TimeRemain))));
    }
    Lines.Add(FString::Printf(TEXT("Pivotal Points: %d / %d"),
        PivotsActivatedDisplay,
        PivotsTotalDisplay));
    Lines.Add(FString::Printf(TEXT("Status: %s"), *StatusText));

    const float StartX = 50.f, StartY = 50.f, LineH = 22.f * TextScale;
    float MaxW = 0.f;
    for (const FString& L : Lines)
    {
        float W, H;
        GetTextSize(L, W, H, HudFont, TextScale);
        MaxW = FMath::Max(MaxW, W);
    }

    const FVector2D Pad = BackgroundPadding;
    DrawRect(FLinearColor(0.f, 0.f, 0.f, BackgroundAlpha),
             StartX - Pad.X, StartY - Pad.Y,
             MaxW + Pad.X * 2.f, Lines.Num() * LineH + Pad.Y * 2.f);

    float Y = StartY;
    for (int32 i = 0; i < Lines.Num(); ++i)
    {
        const bool bIsStatus = (i == Lines.Num() - 1);
        DrawText(Lines[i], bIsStatus ? StatusColor : TextColor, StartX, Y, HudFont, TextScale);
        Y += LineH;
    }

    // Append minimap rendering in the top-right corner.
    if (bShowMapCanvas)
    {
        DrawMinimap(Pawn->GetActorLocation(), StartLoc, EndLoc);
    }
}

FVector2D AMazeHUD::WorldToMinimap(const FVector& WorldPos) const
{
    const float Width  = FMath::Max(1.f, MazeWorldMax.X - MazeWorldMin.X);
    const float Height = FMath::Max(1.f, MazeWorldMax.Y - MazeWorldMin.Y);

    const float NormalizedX = (WorldPos.X - MazeWorldMin.X) / Width;
    const float NormalizedY = (WorldPos.Y - MazeWorldMin.Y) / Height;

    // Invert Y so that higher world Y appears higher on the minimap.
    return FVector2D(NormalizedX, 1.f - NormalizedY);
}


void AMazeHUD::DrawMinimap(const FVector& PlayerLoc, const FVector& StartLoc, const FVector& EndLoc)
{
    if (!Canvas)
    {
        return;
    }

    // Compute minimap rectangle in screen space (top-right corner).
    const float MapW = MapSize.X;
    const float MapH = MapSize.Y;

    const float X = Canvas->ClipX - MapMargin.X - MapW;
    const float Y = MapMargin.Y;

    // Background (filled quad) using DrawRect (AHUD helper).
    DrawRect(MapBackgroundColor, X, Y, MapW, MapH);

    // Static rotation for map (controlled via MarkerRotationDeg).
    const float AngleRad = FMath::DegreesToRadians(MarkerRotationDeg);
    const float CosA = FMath::Cos(AngleRad);
    const float SinA = FMath::Sin(AngleRad);

    auto DrawMarker = [this, X, Y, MapW, MapH, CosA, SinA](const FVector& WorldPos, const FLinearColor& Color)
    {
        if (!Canvas) return;

        FVector2D UV = WorldToMinimap(WorldPos);

        // Optional flips, controlled from HUD settings.
        if (bFlipMapHorizontally)
        {
            UV.X = 1.f - UV.X;
        }
        if (bFlipMapVertically)
        {
            UV.Y = 1.f - UV.Y;
        }

        // Centered coordinates in range [-0.5, 0.5]
        const float U = UV.X - 0.5f;
        const float V = UV.Y - 0.5f;

        // Apply static rotation around center.
        const float RU = U * CosA - V * SinA;
        const float RV = U * SinA + V * CosA;

        // Back to 0..1
        const float RotX = RU + 0.5f;
        const float RotY = RV + 0.5f;

        const float Px = X + RotX * MapW;
        const float Py = Y + RotY * MapH;

        const float S = MarkerSize;
        // Filled marker square using DrawRect (AHUD helper).
        DrawRect(Color, Px - S * 0.5f, Py - S * 0.5f, S, S);
    };

    // Start, End, Player
    DrawMarker(StartLoc, StartColor);
    DrawMarker(EndLoc,   EndColor);
    DrawMarker(PlayerLoc, PlayerColor);

    // TeleportIn markers
    for (AActor* TeleIn : TeleportInActorsCached)
    {
        if (!TeleIn) continue;
        DrawMarker(TeleIn->GetActorLocation(), TeleportInColor);
    }
}
