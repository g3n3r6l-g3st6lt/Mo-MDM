#include "MazeGrid.h"
#include "Algo/Reverse.h"

static void CarveDFS(UMazeGrid* G, const FMazeConfig& Cfg, FRandomStream& Rng)
{
    struct StackEntry { int32 C, R; };
    TArray<StackEntry> Stack;
    auto Neigh = [&](int32 C, int32 R, TArray<TPair<FIntPoint,int32>>& Out){
        Out.Reset();
        const int32 D[4][2]={{0,-1},{1,0},{0,1},{-1,0}};
        for (int32 d=0; d<4; ++d){
            const int32 c=C+D[d][0], r=R+D[d][1];
            if (G->InBounds(c,r) && G->Cells[G->Index(c,r)].Visited==false){
                Out.Add({FIntPoint(c,r), d});
            }
        }
    };
    auto KnockBetween=[&](int32 C0,int32 R0,int32 C1,int32 R1){
        FMazeCell& A = G->Cells[G->Index(C0,R0)];
        FMazeCell& B = G->Cells[G->Index(C1,R1)];
        if (C1==C0 && R1==R0-1){ A.N=false; B.S=false; }
        else if (C1==C0+1 && R1==R0){ A.E=false; B.W=false; }
        else if (C1==C0 && R1==R0+1){ A.S=false; B.N=false; }
        else if (C1==C0-1 && R1==R0){ A.W=false; B.E=false; }
    };

    for (FMazeCell& cell: G->Cells){ cell.N=cell.E=cell.S=cell.W=true; cell.Visited=false; }
    const int32 StartC = 0, StartR = 0;
    G->Cells[G->Index(StartC,StartR)].Visited=true;
    Stack.Add({StartC,StartR});

    TArray<TPair<FIntPoint,int32>> Choices;
    while(Stack.Num()>0){
        auto Curr = Stack.Last();
        Neigh(Curr.C, Curr.R, Choices);
        if (Choices.Num()==0){ Stack.Pop(); continue; }
        const int32 Pick = Rng.RandRange(0, Choices.Num()-1);
        auto Next = Choices[Pick];
        KnockBetween(Curr.C, Curr.R, Next.Key.X, Next.Key.Y);
        G->Cells[G->Index(Next.Key.X, Next.Key.Y)].Visited=true;
        Stack.Add({Next.Key.X,Next.Key.Y});
    }
}

void UMazeGrid::Generate(const FMazeConfig& InConfig)
{
    Rows = InConfig.Rows;
    Cols = InConfig.Cols;
    Cells.SetNum(Rows*Cols);
    FRandomStream Rng(InConfig.Seed);
    CarveDFS(this, InConfig, Rng);
}

TArray<FIntPoint> UMazeGrid::FindPathBFS(FIntPoint Start, FIntPoint Goal) const
{
    TArray<FIntPoint> Empty;
    if (!InBounds(Start.X,Start.Y) || !InBounds(Goal.X,Goal.Y)) return Empty;

    TArray<int32> Parent; Parent.Init(-1, Rows*Cols);
    TQueue<int32> Q;
    const int32 S = Index(Start.X,Start.Y);
    const int32 G = Index(Goal.X,Goal.Y);
    Q.Enqueue(S);
    Parent[S]=S;

    auto Enq=[&](int32 C,int32 R,int32 FromI){
        if (!InBounds(C,R)) return;
        const int32 I = Index(C,R);
        if (Parent[I]!=-1) return;
        Parent[I]=FromI; Q.Enqueue(I);
    };

    while(!Q.IsEmpty()){
        int32 I; Q.Dequeue(I);
        if (I==G) break;
        const int32 C = I%Cols, R = I/Cols;
        const FMazeCell& M = Cells[I];
        if (!M.N) Enq(C, R-1, I);
        if (!M.E) Enq(C+1, R, I);
        if (!M.S) Enq(C, R+1, I);
        if (!M.W) Enq(C-1, R, I);
    }

    if (Parent[G]==-1) return Empty;
    TArray<FIntPoint> Path;
    for (int32 I=G; I!=S; I=Parent[I]) Path.Add({I%Cols, I/Cols});
    Path.Add({S%Cols, S/Cols});
    Algo::Reverse(Path);
    return Path;
}

int32 UMazeGrid::CountOpenSides(int32 C, int32 R) const
{
    if (!InBounds(C,R)) return 0;
    const FMazeCell& M = Cells[Index(C,R)];
    int32 Count=0;
    if (!M.N) ++Count;
    if (!M.E) ++Count;
    if (!M.S) ++Count;
    if (!M.W) ++Count;
    return Count;
}

bool UMazeGrid::IsJunction(int32 C, int32 R) const
{
    return CountOpenSides(C,R) >= 3;
}
