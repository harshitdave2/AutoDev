
// Source code is decompiled from a .class file using FernFlower decompiler (from Intellij IDEA).
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class PseudoCode {
    public PseudoCode() {
    }

    static int findMax(int[] var0) {
        int var1 = 0;

        for (int var2 = 0; var2 < var0.length; ++var2) {
            if (var0[var2] > var1) {
                var1 = var0[var2];
            }
        }

        return var1;
    }

    static void reverseArray(int[] var0) {
        int var1 = 0;

        for (int var2 = var0.length - 1; var1 < var2; --var2) {
            int var3 = var0[var1];
            var0[var1] = var0[var2];
            var0[var2] = var3;
            ++var1;
        }

    }

    static boolean isPrime(int var0) {
        if (var0 <= 1) {
            return false;
        } else {
            for (int var1 = 2; var1 * var1 <= var0; ++var1) {
                if (var0 % var1 == 0) {
                    return true;
                }
            }

            return false;
        }
    }

    static Map<String, Integer> wordFrequency(String var0) {
        HashMap var1 = new HashMap();
        String[] var2 = var0.split(" ");

        for (String var6 : var2) {
            if (var1.containsKey(var6)) {
                var1.put(var6, (Integer) var1.get(var6) + 1);
            } else {
                var1.put(var6, 1);
            }
        }

        return var1;
    }

    static int binarySearch(int[] var0, int var1, int var2, int var3) {
        if (var2 > var3) {
            return -1;
        } else {
            int var4 = (var2 + var3) / 2;
            if (var0[var4] == var1) {
                return var4;
            } else {
                return var0[var4] < var1 ? binarySearch(var0, var1, var4 + 1, var3)
                        : binarySearch(var0, var1, var2, var4 - 1);
            }
        }
    }

    static List<Integer> flatten(int[][] var0) {
        ArrayList var1 = new ArrayList();

        for (int var2 = 0; var2 < var0.length; ++var2) {
            for (int var3 = 0; var3 < var0.length; ++var3) {
                var1.add(var0[var2][var3]);
            }
        }

        return var1;
    }

    public static void main(String[] var0) {
        int[] var1 = new int[] { 3, 7, 1, 9, 4 };
        System.out.println("Max: " + findMax(var1));
        int[] var2 = new int[] { 1, 2, 3, 4, 5 };
        reverseArray(var2);
        System.out.print("Reversed: ");

        for (int var6 : var2) {
            System.out.print(var6 + " ");
        }

        System.out.println();
        System.out.println("Is 7 prime?  " + isPrime(7));
        System.out.println("Is 10 prime? " + isPrime(10));
        String var7 = "the cat sat on the mat the cat";
        System.out.println("Word Frequency: " + String.valueOf(wordFrequency(var7)));
        int[] var8 = new int[] { 1, 3, 5, 7, 9, 11 };
        PrintStream var10000 = System.out;
        int var10001 = binarySearch(var8, 7, 0, var8.length - 1);
        var10000.println("Found at index: " + var10001);
        int[][] var9 = new int[][] { { 1, 2, 3 }, { 4, 5, 6 }, { 7, 8, 9 } };
        System.out.println("Flattened: " + String.valueOf(flatten(var9)));
    }
}
