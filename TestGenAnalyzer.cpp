#include "clang/StaticAnalyzer/Core/Checker.h"
#include "clang/StaticAnalyzer/Core/CheckerManager.h"
#include "clang/StaticAnalyzer/Core/PathSensitive/MemRegion.h"
#include "clang/StaticAnalyzer/Core/PathSensitive/RangedConstraintManager.h"
#include "clang/StaticAnalyzer/Frontend/CheckerRegistry.h"
#include "clang/StaticAnalyzer/Core/PathSensitive/CheckerContext.h"
#include "clang/StaticAnalyzer/Core/PathSensitive/ProgramState.h"
#include "clang/StaticAnalyzer/Core/PathSensitive/SVals.h"
#include "clang/StaticAnalyzer/Core/PathSensitive/SymbolManager.h"
#include "clang/StaticAnalyzer/Core/PathSensitive/ConstraintManager.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Support/JSON.h"
#include <map>
#include <string>

using namespace clang;
using namespace ento;

namespace {

struct ParamInfo {
    SymbolRef Sym;
    std::string Name;
    QualType Type;
};

class TestGenAnalyzer : public Checker<
    check::BeginFunction,
    check::EndFunction
> {
    mutable std::vector<ParamInfo> Params;
    mutable unsigned PathCount = 0;

public:

    void checkBeginFunction(CheckerContext &C) const {
        Params.clear();

        const LocationContext *LC = C.getLocationContext();
        const FunctionDecl *FD = dyn_cast<FunctionDecl>(LC->getDecl());

        if (!FD)
            return;

        ProgramStateRef State = C.getState();

        for (const ParmVarDecl *P : FD->parameters()) {
            const MemRegion *MR =
                C.getSValBuilder()
                    .getRegionManager()
                    .getVarRegion(P, LC);

            SVal Val = State->getSVal(MR);

            if (auto SymVal = Val.getAs<nonloc::SymbolVal>()) {
                ParamInfo Info;
                Info.Sym = SymVal->getSymbol();
                Info.Name = P->getNameAsString();
                Info.Type = P->getType();
                Params.push_back(Info);
            }
        }
    }

    /// 提取约束并生成测试用例
    void checkEndFunction(const ReturnStmt *Ret, CheckerContext &C) const {
        ProgramStateRef State = C.getState();

        const LocationContext *LC = C.getLocationContext();
        const FunctionDecl *FD = dyn_cast<FunctionDecl>(LC->getDecl());

        if (!FD)
            return;

        PathCount++;

        llvm::errs() << "\n=== Path #" << PathCount << " ===\n";
        llvm::errs() << "Function: " << FD->getNameAsString() << "\n";

        // 获取约束映射
        ConstraintMap Constraints = getConstraintMap(State);

        // 构建 JSON 输出
        llvm::json::Object TestCase;
        llvm::json::Array ConstraintsArray;

        // 遍历每个参数，提取其约束
        for (const auto &ParamInfo : Params) {
            SymbolRef Sym = ParamInfo.Sym;

            // 查找该符号的约束
            const RangeSet *ParamRS = Constraints.lookup(Sym);

            llvm::json::Object ParamConstraint;
            ParamConstraint["name"] = ParamInfo.Name;
            ParamConstraint["type"] = ParamInfo.Type.getAsString();

            if (ParamRS && !ParamRS->isEmpty()) {
                // 提取范围约束
                llvm::json::Array Ranges;

                for (const auto &Range : *ParamRS) {
                    llvm::json::Object RangeObj;
                    RangeObj["from"] = (int64_t)Range.From().getExtValue();
                    RangeObj["to"] = (int64_t)Range.To().getExtValue();
                    Ranges.push_back(std::move(RangeObj));
                }

                ParamConstraint["ranges"] = std::move(Ranges);

                // 如果是单个具体值，直接提取
                if (const llvm::APSInt *ConcreteVal = ParamRS->getConcreteValue()) {
                    ParamConstraint["concrete_value"] = (int64_t)ConcreteVal->getExtValue();
                }
            } else {
                // 无约束，表示任意值
                ParamConstraint["constraint"] = "unconstrained";
            }

            ConstraintsArray.push_back(std::move(ParamConstraint));
        }

        TestCase["parameters"] = std::move(ConstraintsArray);

        // 提取返回值（如果有）
        if (Ret) {
            SVal RetVal = State->getSVal(Ret->getRetValue(), LC);
            if (auto ConcreteInt = RetVal.getAs<nonloc::ConcreteInt>()) {
                TestCase["return_value"] = (int64_t)ConcreteInt->getValue().getExtValue();
            } else if (auto SymVal = RetVal.getAs<nonloc::SymbolVal>()) {
                // 返回值是符号，尝试获取其约束
                SymbolRef RetSym = SymVal->getSymbol();
                const RangeSet *RetRS = Constraints.lookup(RetSym);
                if (RetRS && RetRS->getConcreteValue()) {
                    TestCase["return_value"] = (int64_t)RetRS->getConcreteValue()->getExtValue();
                }
            }
        }

        // 输出 JSON
        llvm::errs() << "[TestCase JSON]\n";
        llvm::errs() << llvm::formatv("{0:2}", llvm::json::Value(std::move(TestCase))) << "\n";
        llvm::errs() << "=================\n";
    }
};

} // namespace



/// =====================================
/// register
/// =====================================
extern "C" void clang_registerCheckers(CheckerRegistry &registry) {
  registry.addChecker<TestGenAnalyzer>(
      "testgen.TestGenAnalyzer",
      "Simple Test Generation Analyzer",
      "");
}

extern "C" const char clang_analyzerAPIVersionString[] =
    "LLVM18";