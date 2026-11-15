import java.util.ArrayList;
import java.util.List;

public class type_cast {
    static List<Integer> doubleAll(List<?> values) {
        List<Integer> result = new ArrayList<>();
        for (Object value : values) {
            if (value instanceof Integer) {
                result.add(((Integer) value) * 2);
            }
        }
        return result;
    }

    public static void main(String[] args) {
        List<Object> mixed = new ArrayList<>();
        mixed.add(1);
        mixed.add(2);
        mixed.add("three");
        mixed.add(4);

        List<Integer> doubled = doubleAll(mixed);
        System.out.println("Doubled: " + doubled);
    }
}
