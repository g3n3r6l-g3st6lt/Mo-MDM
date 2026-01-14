// MazeStart.cpp

#include "MazeStart.h"
#include "Components/SceneComponent.h"

AMazeStart::AMazeStart()
{
    Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    RootComponent = Root;

    // You can move/rotate/scale this in-editor.
    SetActorHiddenInGame(true); // invisible during play
}

