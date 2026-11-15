public class null_ptr {
    static String findEmail(String[][] users, String username) {
        for (String[] user : users) {
            if (user[0].equals(username)) return user[1];
        }
        return null;
    }

    static String formatUser(String[][] users, String username) {
        String email = findEmail(users, username);
        if (email == null) {
            return username.toUpperCase() + " <not found>";
        }
        return username.toUpperCase() + " <" + email.toUpperCase() + ">";
    }

    public static void main(String[] args) {
        String[][] users = {
            {"alice", "alice@example.com"},
            {"bob", "bob@example.com"}
        };
        System.out.println(formatUser(users, "alice"));
        System.out.println(formatUser(users, "charlie"));
    }
}
